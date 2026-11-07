"""LLM gateway: the ONLY place the app talks to a model.

Controls: provider/base-URL allowlist, key from env only (never logged/returned), timeout, bounded retries with
backoff, circuit breaker, token cap, strict JSON-schema validation of output. Callers must pass already-redacted,
non-quarantined, structured data (see security.injection.build_llm_context for free text)."""
import json
import time
from typing import Callable, Optional, Type

import httpx
from pydantic import BaseModel, ValidationError

# provider -> (base_url, needs_key). Anything else is refused: no arbitrary endpoints.
PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1", True),      # free tier; states it does not train on API data
    "ollama": ("http://127.0.0.1:11434/v1", False),         # local model; data never leaves your machine
}


class LLMError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class LLMGateway:
    def __init__(self, provider: str, api_key: str, model: str, transport=None, timeout: float = 20.0,
                 max_retries: int = 2, backoff: float = 0.5, max_tokens: int = 1200,
                 breaker_threshold: int = 3, breaker_cooldown: float = 60.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.provider = provider if provider in PROVIDERS else "none"
        self.model, self.max_tokens = model, max_tokens
        self._key = api_key
        self._transport, self._timeout = transport, timeout
        self._retries, self._backoff = max_retries, backoff
        self._fails, self._open_until = 0, 0.0
        self._thr, self._cool, self._clock, self._sleep = breaker_threshold, breaker_cooldown, clock, sleep

    def __repr__(self):  # never expose the key
        return f"LLMGateway(provider={self.provider!r}, model={self.model!r})"

    @property
    def enabled(self) -> bool:
        if self.provider == "none":
            return False
        return bool(self._key) or not PROVIDERS[self.provider][1]

    def complete_json(self, system: str, payload: dict, schema: Type[BaseModel]) -> tuple[BaseModel, int]:
        """Returns (validated_model, tokens_used)."""
        if not self.enabled:
            raise LLMError("LLM is not configured", 503)
        if self._clock() < self._open_until:
            raise LLMError("LLM temporarily unavailable (circuit open)", 503)
        base, needs_key = PROVIDERS[self.provider]
        headers = {"Content-Type": "application/json"}
        if needs_key:
            headers["Authorization"] = f"Bearer {self._key}"
        body = {"model": self.model, "temperature": 0, "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": json.dumps(payload, ensure_ascii=True)}]}
        if "gpt-oss" in self.model:  # reasoning models: keep thinking short so the JSON answer fits the token cap
            body["reasoning_effort"] = "low"
        last = "unknown error"
        with httpx.Client(transport=self._transport, timeout=self._timeout, follow_redirects=False) as client:
            for attempt in range(self._retries + 1):
                try:
                    r = client.post(f"{base}/chat/completions", headers=headers, json=body)
                    if r.status_code in (429, 500, 502, 503, 504):
                        last = f"provider returned {r.status_code}"
                    elif r.status_code != 200:
                        self._record_failure()
                        raise LLMError(f"provider rejected the request ({r.status_code})")
                    else:
                        data = r.json()
                        content = data["choices"][0]["message"]["content"]
                        if not content:
                            raise LLMError("Model returned empty output")
                        tokens = int(data.get("usage", {}).get("total_tokens", self.max_tokens))
                        try:
                            parsed = schema.model_validate(json.loads(content))
                        except (ValueError, ValidationError):
                            raise LLMError("Model output failed schema validation")
                        self._fails = 0
                        return parsed, tokens
                except (httpx.TimeoutException, httpx.TransportError):
                    last = "network error or timeout"
                except (KeyError, IndexError, TypeError, ValueError):
                    raise LLMError("Malformed provider response")
                if attempt < self._retries:
                    self._sleep(self._backoff * (2 ** attempt))
        self._record_failure()
        raise LLMError(f"LLM unavailable: {last}", 503)

    def _record_failure(self):
        self._fails += 1
        if self._fails >= self._thr:
            self._open_until = self._clock() + self._cool
            self._fails = 0
