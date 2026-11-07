"""Gap & Learning Planner (deterministic). Turns eligibility + scoring results into an honest, deadline-aware plan.

Categories (blueprint section 2, step 9):
  NOT_FIXABLE_FOR_THIS_VACANCY  - e.g. visa or graduation-window mismatch
  CONFIRMATION_REQUIRED         - a fact the candidate must confirm or correct
  OMITTED_EVIDENCE              - the skill is in evidence the candidate has not approved yet
  SHORT_TERM_FIXABLE            - a small proof task can close it (days)
  LONG_TERM                     - needs sustained learning (weeks or more)
A CV can only change after the candidate adds proof as evidence and approves it (enforced by the resume module)."""
from datetime import date
from typing import Optional

from ..schemas import Level
from . import evidence as ev

# Controlled learning links: official documentation only.
OFFICIAL_DOCS = {
    "python": "https://docs.python.org/3/tutorial/",
    "sql": "https://www.postgresql.org/docs/current/tutorial.html",
    "postgresql": "https://www.postgresql.org/docs/current/tutorial.html",
    "docker": "https://docs.docker.com/get-started/",
    "kubernetes": "https://kubernetes.io/docs/tutorials/kubernetes-basics/",
    "fastapi": "https://fastapi.tiangolo.com/tutorial/",
    "git": "https://git-scm.com/book/en/v2",
    "pandas": "https://pandas.pydata.org/docs/getting_started/index.html",
    "numpy": "https://numpy.org/doc/stable/user/absolute_beginners.html",
    "pytorch": "https://pytorch.org/tutorials/",
    "tensorflow": "https://www.tensorflow.org/tutorials",
    "scikit-learn": "https://scikit-learn.org/stable/tutorial/index.html",
    "machine learning": "https://scikit-learn.org/stable/tutorial/index.html",
    "react": "https://react.dev/learn",
    "javascript": "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide",
    "typescript": "https://www.typescriptlang.org/docs/handbook/intro.html",
    "ci/cd": "https://docs.github.com/en/actions",
    "linux": "https://ubuntu.com/tutorials/command-line-for-beginners",
    "japanese": "https://www.jlpt.jp/e/",
}

# Proof tasks a candidate can realistically finish in days, with an estimate in days.
SHORT_TASKS = {
    "docker": (3, "Containerise one of your existing projects with a Dockerfile and document how to run it."),
    "git": (2, "Publish a project with a clean commit history, README and .gitignore."),
    "sql": (4, "Write and document 10 analytical SQL queries (joins, GROUP BY, window functions) on a public dataset."),
    "postgresql": (4, "Run a project against PostgreSQL locally and document the schema and queries."),
    "fastapi": (4, "Expose one of your models or scripts as a FastAPI endpoint with input validation and tests."),
    "rest api": (3, "Build a small REST API with documented endpoints and tests."),
    "pandas": (3, "Clean and analyse a public dataset in a notebook with pandas; summarise findings."),
    "numpy": (2, "Implement a small numerical routine with NumPy and compare it to a pure-Python version."),
    "ci/cd": (2, "Add a GitHub Actions workflow that runs your tests on every push."),
    "linux": (3, "Write and document a few shell scripts that automate a real task on Linux."),
    "excel": (2, "Build a documented spreadsheet analysis with formulas and a chart."),
    "tableau": (3, "Publish a small dashboard on a public dataset and describe the insights."),
    "flask": (3, "Build a small Flask app with tests."),
    "llm": (4, "Build a small, documented LLM-powered tool with input validation and an evaluation of its outputs."),
}
LONG_DAYS = 30


def _deadline_days(deadline: Optional[str], today: date) -> Optional[int]:
    if not deadline:
        return None
    return (date.fromisoformat(deadline) - today).days


def _feasibility(days_needed: int, days_left: Optional[int]) -> str:
    if days_left is None:
        return "NO_DEADLINE_SET"
    if days_left < 0:
        return "DEADLINE_PASSED"
    return "FITS_BEFORE_DEADLINE" if days_needed <= days_left else "NOT_REALISTIC_BEFORE_DEADLINE"


def plan(requirements, evidence_items: list, eligibility: dict, deadline: Optional[str] = None,
         today: Optional[date] = None) -> dict:
    today = today or date.today()
    days_left = _deadline_days(deadline, today)
    items = []

    for g in eligibility["gates"]:
        if g["status"] == "NOT_MET" and g["kind"] in ("VISA", "GRADUATION", "WORK_AUTH"):
            items.append({"category": "NOT_FIXABLE_FOR_THIS_VACANCY", "topic": g["kind"], "message": g["message"],
                          "action": "Consider an alternative route or a different vacancy; this cannot be fixed with a CV change.",
                          "source_quote": g["source_quote"]})
        elif g["status"] == "NOT_MET" and g["kind"] in ("LANGUAGE", "EXPERIENCE"):
            items.append({"category": "LONG_TERM", "topic": g["kind"], "message": g["message"],
                          "action": ("Plan for the required certificate/level; add the certificate as evidence once you hold it."
                                     if g["kind"] == "LANGUAGE" else "Build experience over time; this is not fixable for this vacancy now."),
                          "estimate_days": None, "feasibility": "NOT_REALISTIC_BEFORE_DEADLINE" if days_left is not None else "NO_DEADLINE_SET",
                          "learn_link": OFFICIAL_DOCS.get(g["required"].get("language", "")), "source_quote": g["source_quote"]})
        elif g["status"] in ("CONFIRMATION_REQUIRED", "SOFT_MISMATCH"):
            items.append({"category": "CONFIRMATION_REQUIRED" if g["status"] == "CONFIRMATION_REQUIRED" else "LONG_TERM",
                          "topic": g["kind"], "message": g["message"],
                          "action": "Update your profile with the correct fact, or ask the recruiter to confirm.",
                          "source_quote": g["source_quote"]})

    approved = ev.usable(evidence_items)
    pending = [e for e in evidence_items if e["verification_status"] not in ev.USABLE]
    have = set().union(*(ev.evidence_skills(e) for e in approved)) if approved else set()
    seen = set()
    for r in requirements:
        if r.level == Level.UNCLEAR:
            continue
        for skill in r.skills:
            if skill in have or skill in seen:
                continue
            seen.add(skill)
            base = {"topic": skill, "requirement_level": r.level.value, "source_quote": r.span.quote,
                    "learn_link": OFFICIAL_DOCS.get(skill)}
            unapproved = [e["id"] for e in pending if skill in ev.evidence_skills(e)]
            if unapproved:
                items.append(base | {"category": "OMITTED_EVIDENCE", "evidence_ids": unapproved,
                                     "message": f"You have evidence mentioning {skill} that is not approved yet.",
                                     "action": "Review that evidence and approve it only if it is accurate.",
                                     "estimate_days": 0, "feasibility": _feasibility(0, days_left)})
            elif skill in SHORT_TASKS:
                d, task = SHORT_TASKS[skill]
                items.append(base | {"category": "SHORT_TERM_FIXABLE", "estimate_days": d, "feasibility": _feasibility(d, days_left),
                                     "message": f"{skill} is {'required' if r.level == Level.MANDATORY else 'preferred'} and I found no approved evidence for it.",
                                     "action": task + " Then add it as evidence with a proof link and approve it."})
            else:
                items.append(base | {"category": "LONG_TERM", "estimate_days": LONG_DAYS, "feasibility": _feasibility(LONG_DAYS, days_left),
                                     "message": f"{skill} is {'required' if r.level == Level.MANDATORY else 'preferred'} and I found no approved evidence for it.",
                                     "action": (f"Build a small, documented project that genuinely uses {skill}. "
                                                "If you already have such work, add it as evidence instead of relearning.")})

    order = {"NOT_FIXABLE_FOR_THIS_VACANCY": 0, "CONFIRMATION_REQUIRED": 1, "OMITTED_EVIDENCE": 2, "SHORT_TERM_FIXABLE": 3, "LONG_TERM": 4}
    items.sort(key=lambda x: (order[x["category"]], x.get("requirement_level") != "MANDATORY"))
    return {"deadline": deadline, "days_left": days_left, "items": items,
            "summary": {k: sum(1 for i in items if i["category"] == k) for k in order},
            "proof_gate": "Your CV changes only after you add proof as evidence and approve it.",
            "note": "Estimates are rough planning guides, not promises."}
