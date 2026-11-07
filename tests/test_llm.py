import itertools
import json

import httpx

from app.llm.gateway import LLMError, LLMGateway
from app.api import Explanation
from tests.conftest import read_fixture, signup

KEY = "gsk_TEST_KEY_DO_NOT_LEAK"
GOOD = {"degree": "B.Tech", "graduation_year": 2028, "languages": {"japanese": "N5"}, "needs_sponsorship": False,
        "consents": {"parsing": True, "llm_processing": True}}
JOB = {"title": "ML Intern", "company": "Synthetic Co", "description_text": read_fixture("job_ml_intern.txt"), "last_checked": "2026-10-30"}
OK = {"summary": "The posting asks for Japanese N3 and your declared level is N5, so this is an eligibility risk for this vacancy.",
      "next_steps": ["Confirm your Japanese level.", "Consider roles without a Japanese requirement."]}


_n = itertools.count()


def reply(content, tokens=120, status=200):
    return httpx.Response(status, json={"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}],
                                        "usage": {"total_tokens": tokens}})


def make_env(make_client, handler, **kw):
    seen = []
    def h(req):
        seen.append(req)
        return handler(req)
    c = make_client(llm=httpx.MockTransport(h), llm_provider="groq", llm_api_key=KEY, llm_backoff=0, **kw)
    hd = signup(c, f"user{next(_n)}@example.test")
    return c, hd, seen


def job(c, hd, consent=True):
    c.put("/profile", json=GOOD if consent else GOOD | {"consents": {"parsing": True}}, headers=hd)
    return c.post("/jobs", json=JOB, headers=hd).json()["id"]


def test_explain_happy_path_and_privacy(make_client):
    c, hd, seen = make_env(make_client, lambda r: reply(OK))
    r = c.post(f"/jobs/{job(c, hd)}/explain", headers=hd)
    assert r.status_code == 200 and "not an employer ats score" in r.json()["disclaimer"].lower()
    req = seen[0]
    assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    sent = req.content.decode()
    assert "Visa sponsorship is not available" not in sent and "Machine Learning Intern" not in sent  # no raw job text
    assert "alice@example.test" not in sent
    assert KEY not in r.text and KEY not in json.dumps(c.get("/audit", headers=hd).json())


def test_explain_injection_text_never_reaches_model(make_client):
    c, hd, seen = make_env(make_client, lambda r: reply({"summary": "I could not verify some facts.", "next_steps": ["Approve evidence for Python."]}))
    c.put("/profile", json=GOOD, headers=hd)
    jid = c.post("/jobs", json=JOB | {"description_text": read_fixture("job_injection.txt")}, headers=hd).json()["id"]
    assert c.post(f"/jobs/{jid}/explain", headers=hd).status_code == 200
    assert "ignore all previous" not in seen[0].content.decode().lower()


def test_requires_consent_and_configuration(make_client):
    c, hd, seen = make_env(make_client, lambda r: reply(OK))
    assert c.post(f"/jobs/{job(c, hd, consent=False)}/explain", headers=hd).status_code == 403 and not seen
    c2 = make_client()  # provider none
    h2 = signup(c2, "other@example.test")
    assert c2.post(f"/jobs/{job(c2, h2)}/explain", headers=h2).status_code == 503


def test_object_authorization(make_client):
    c, a, _ = make_env(make_client, lambda r: reply(OK))
    jid = job(c, a)
    b = signup(c, "b@example.test")
    c.put("/profile", json=GOOD, headers=b)
    assert c.post(f"/jobs/{jid}/explain", headers=b).status_code == 404


def test_token_budget(make_client):
    c, hd, _ = make_env(make_client, lambda r: reply(OK, tokens=500), llm_tokens_per_day=600)
    jid = job(c, hd)
    codes = [c.post(f"/jobs/{jid}/explain", headers=hd).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_invented_number_or_promise_is_discarded(make_client):
    for bad in ({"summary": "You scored 87 out of 100.", "next_steps": []},
                {"summary": "This CV is perfect and will be shortlisted.", "next_steps": []},
                {"summary": "Fine.", "next_steps": ["We guarantee an interview."]}):
        c, hd, _ = make_env(make_client, lambda r, b=bad: reply(b))
        assert c.post(f"/jobs/{job(c, hd)}/explain", headers=hd).status_code == 502


def test_schema_failure_extra_fields_and_garbage(make_client):
    for bad in ('not json', json.dumps({"summary": "x", "next_steps": [], "extra": 1}), json.dumps({"summary": "x"})):
        c, hd, _ = make_env(make_client, lambda r, b=bad: reply(b))
        assert c.post(f"/jobs/{job(c, hd)}/explain", headers=hd).status_code == 502


def test_retries_then_circuit_breaker():
    calls = []
    def h(req):
        calls.append(1)
        return httpx.Response(503)
    t = [0.0]
    g = LLMGateway("groq", KEY, "m", transport=httpx.MockTransport(h), max_retries=1, backoff=0, breaker_threshold=2,
                   breaker_cooldown=60, clock=lambda: t[0], sleep=lambda s: None)
    for _ in range(2):
        try:
            g.complete_json("s", {}, Explanation)
        except LLMError as e:
            assert e.status == 503
    assert len(calls) == 4  # 2 requests x (1 try + 1 retry)
    try:
        g.complete_json("s", {}, Explanation)
    except LLMError as e:
        assert "circuit open" in str(e)
    assert len(calls) == 4  # breaker short-circuited, no network call
    t[0] = 61
    try:
        g.complete_json("s", {}, Explanation)
    except LLMError:
        pass
    assert len(calls) == 6


def test_provider_allowlist_and_key_not_in_repr():
    g = LLMGateway("evil", KEY, "m")
    assert not g.enabled and KEY not in repr(g)
    assert not LLMGateway("groq", "", "m").enabled      # key required for groq
    assert LLMGateway("ollama", "", "m").enabled        # local needs no key
