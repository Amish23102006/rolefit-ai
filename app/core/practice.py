"""Assessment & Interview Readiness (deterministic). Generates ORIGINAL practice only.

Integrity rules: questions come from RoleFit's own template bank (written for this project, not copied from any
employer or leaked test); nothing is generated while the candidate says a live assessment is in progress."""
import hashlib
import random

from ..schemas import Level
from . import evidence as ev

TECH = {
    "python": [
        "Write a function that returns the k most frequent words in a text, ignoring case and punctuation. State its time complexity.",
        "Explain the difference between a list and a generator in Python and when you would choose each.",
        "Implement a decorator that retries a function up to 3 times with exponential backoff. How would you test it?",
    ],
    "sql": [
        "Given orders(id, user_id, amount, created_at), write a query returning each user's largest order in the last 30 days.",
        "Explain the difference between WHERE and HAVING with an example.",
        "How would you find duplicate rows in a table and keep only the newest one?",
    ],
    "machine learning": [
        "How would you detect and prevent data leakage when building a model on time-ordered data?",
        "Your classifier has 95% accuracy but the positive class is 3% of the data. What would you check next?",
        "Explain the bias-variance trade-off using a model you have built.",
    ],
    "deep learning": [
        "Explain why a training loss might decrease while validation loss increases, and three ways to respond.",
        "What does batch normalisation do, and when can it hurt?",
    ],
    "pytorch": [
        "Write a minimal PyTorch training loop for a classifier, including evaluation mode and gradient zeroing.",
        "How would you debug a model whose loss becomes NaN after a few iterations?",
    ],
    "nlp": [
        "Compare TF-IDF features with sentence embeddings for a text-classification task. When is each a better choice?",
        "How would you evaluate a text classifier fairly when labels are noisy?",
    ],
    "computer vision": [
        "How would you build a defect detector when only 50 defective images exist?",
        "Explain how data augmentation can introduce label errors in an image task.",
    ],
    "docker": [
        "Write a Dockerfile for a Python web API that runs as a non-root user. Explain each line.",
        "How would you reduce the size of a Docker image for a Python application?",
    ],
    "fastapi": [
        "Design a FastAPI endpoint that accepts a file upload safely. What limits and validations would you add?",
        "How do dependency-injected authentication checks work in FastAPI?",
    ],
    "git": ["Explain how you would recover from accidentally committing a secret to a Git repository."],
    "llm": [
        "How would you defend an LLM application against prompt injection hidden inside a user-uploaded document?",
        "How would you measure whether an LLM-generated summary is factually grounded in its source?",
    ],
    "kubernetes": ["Explain the difference between a Deployment and a StatefulSet and when you would use each."],
    "java": ["Explain how HashMap handles collisions and what changes when many keys collide."],
    "javascript": ["Explain the event loop and how a Promise callback is scheduled relative to setTimeout."],
    "react": ["How would you prevent unnecessary re-renders in a React list with 1,000 items?"],
    "aws": ["How would you store application secrets on AWS without putting them in code or environment files?"],
}
GENERIC_TECH = "Describe a problem you solved with {skill}. What alternatives did you consider, and why did you choose this approach?"
BEHAVIOURAL = [
    "Tell me about a time you disagreed with a teammate on a technical decision. What did you do and what happened?",
    "Describe a project that did not go as planned. What did you learn, and what would you change?",
    "Tell me about a time you had to learn a new tool quickly to meet a deadline.",
    "Describe how you handled receiving critical feedback on your work.",
]
JAPAN = [
    "Prepare a 1-minute self-introduction (自己紹介) in Japanese at the level you have declared, and an English version.",
    "Why do you want to work in Japan, and how have you prepared for working in a Japanese team?",
    "How would you handle a situation where a decision is made by consensus (根回し) and you were not consulted?",
]


def _rng(*parts) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16))


def generate(job: dict, requirements, evidence_items: list, mode: str, count: int, seed: str) -> dict:
    rng = _rng(seed, mode, str(count))
    approved = ev.usable(evidence_items)
    skills = []
    for level in (Level.MANDATORY, Level.PREFERRED, Level.UNCLEAR):
        for r in requirements:
            if r.level == level:
                skills += [s for s in r.skills if s not in skills]
    questions = []

    if mode in ("technical", "mixed"):
        for s in skills:
            bank = TECH.get(s) or [GENERIC_TECH.format(skill=s)]
            q = rng.choice(bank)
            questions.append({"type": "TECHNICAL", "skill": s, "question": q,
                              "why": f"The posting lists {s}.", "source": "RoleFit original template bank"})
    if mode in ("project", "mixed"):
        for e in approved[:6]:
            questions.append({"type": "PROJECT_DEEP_DIVE", "evidence_id": e["id"],
                              "question": f"Walk me through '{e['title']}': the problem, your own contribution, and how you would prove this claim: \"{e['claim_text']}\"",
                              "why": "Interviewers test every claim on your CV.", "source": "Your approved evidence"})
    if mode in ("behavioural", "mixed"):
        for q in rng.sample(BEHAVIOURAL, k=min(2 if mode == "mixed" else 4, len(BEHAVIOURAL))):
            questions.append({"type": "BEHAVIOURAL", "question": q, "why": "Use the STAR structure: Situation, Task, Action, Result.",
                              "source": "RoleFit original template bank"})
    text = (job.get("description_text", "") + " " + job.get("title", "")).lower()
    if "japan" in text or "japanese" in text or "tokyo" in text:
        for q in JAPAN[: (1 if mode != "japan" else 3)]:
            questions.append({"type": "JAPAN_SPECIFIC", "question": q, "why": "The posting is Japan-related.",
                              "source": "RoleFit original template bank"})
    rng.shuffle(questions)
    return {"mode": mode, "questions": questions[:count],
            "integrity": "Original practice questions only. Do not use RoleFit AI during a live assessment or interview.",
            "note": "Questions are generic practice aligned to the posting's skills, not predictions of the employer's real test."}
