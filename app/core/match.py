"""Skill match report: compares a posting's extracted skills with the candidate's approved evidence and the
skills mentioned in their uploaded CV. Only approved evidence counts as proven; CV mentions are shown separately."""
from ..schemas import Level
from . import evidence as ev
from .skills import find_skills


def cv_skills(documents: list) -> set:
    """Skills mentioned in the candidate's uploaded, non-quarantined CVs (self-declared, not proven)."""
    out = set()
    for d in documents:
        if not d.get("quarantined"):
            out |= find_skills(d.get("text", ""))
    return out


def report(requirements, evidence_items: list, cv: set) -> dict:
    proven = set().union(*(ev.evidence_skills(e) for e in ev.usable(evidence_items))) if ev.usable(evidence_items) else set()
    rows, seen = [], set()
    for level in (Level.MANDATORY, Level.PREFERRED, Level.UNCLEAR):
        for r in requirements:
            if r.level != level:
                continue
            for s in r.skills:
                if s in seen:
                    continue
                seen.add(s)
                status = "PROVEN_BY_APPROVED_EVIDENCE" if s in proven else "IN_CV_NOT_YET_EVIDENCED" if s in cv else "MISSING"
                rows.append({"skill": s, "level": level.value, "status": status, "source_quote": r.span.quote})
    must = [x for x in rows if x["level"] == "MANDATORY"]
    have = lambda xs, st: sum(1 for x in xs if x["status"] in st)
    pct = lambda xs, st: round(100 * have(xs, st) / len(xs)) if xs else None
    both = ("PROVEN_BY_APPROVED_EVIDENCE", "IN_CV_NOT_YET_EVIDENCED")
    return {"skills": rows,
            "required_skills": [x["skill"] for x in must],
            "missing_required": [x["skill"] for x in must if x["status"] == "MISSING"],
            "proven_required_pct": pct(must, ("PROVEN_BY_APPROVED_EVIDENCE",)),
            "cv_or_proven_required_pct": pct(must, both),
            "all_skills_cv_or_proven_pct": pct(rows, both),
            "note": "Proven = in evidence you approved. 'In CV' = mentioned in an uploaded resume but not yet added as evidence."}
