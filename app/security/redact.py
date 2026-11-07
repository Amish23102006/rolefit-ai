"""PII/secret redaction applied before model calls and before anything is logged."""
import re

_RULES = [
    (re.compile(r"\b(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,})\b"), "[SECRET]"),
    (re.compile(r"(?i)\b(token|key|secret|password|passwd|pwd)=[^&\s]+"), r"\1=[SECRET]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"(?<![\w])\+?\d[\d\s().-]{8,}\d(?![\w])"), "[PHONE_OR_ID]"),
]


def redact(text: str) -> str:
    for rx, repl in _RULES:
        text = rx.sub(repl, text)
    return text
