"""Eligibility gate: runs BEFORE resume optimisation. Never infers missing facts."""
from ..schemas import GateStatus, Level, Profile
from .requirements import degree_level

_RANK = {"N5": 1, "N4": 2, "N3": 3, "N2": 4, "N1": 5, "A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}


def _scale(level: str):
    return "JLPT" if level.startswith("N") else "CEFR"


def _check(gate, profile: Profile):
    """Return (status, candidate_value, message) for one gate."""
    k, p = gate.kind, gate.params
    if k == "LANGUAGE":
        lang, need = p["language"], p["level"]
        have = {a.lower(): b.upper() for a, b in profile.languages.items()}.get(lang)
        if not have:
            return GateStatus.CONFIRMATION_REQUIRED, None, f"The posting mentions {lang.title()} {need}. I could not verify your {lang.title()} level; please confirm it."
        if have not in _RANK or _scale(have) != _scale(need):
            return GateStatus.CONFIRMATION_REQUIRED, have, f"Your declared level ({have}) is on a different scale from {need}; please confirm."
        ok = _RANK[have] >= _RANK[need]
        return (GateStatus.MET if ok else GateStatus.NOT_MET), have, (
            f"{lang.title()} {need} required; you declared {have} (self-declared, not yet backed by a certificate)."
            if ok else f"The posting requires {lang.title()} {need}. Your declared level is {have}. This is an eligibility risk for this vacancy.")
    if k == "GRADUATION":
        yrs, op, gy = p["years"], p["op"], profile.graduation_year
        if gy is None:
            return GateStatus.CONFIRMATION_REQUIRED, None, "The posting states a graduation window. Please confirm your graduation year."
        ok = (gy in yrs if op == "in" else min(yrs) <= gy <= max(yrs) if op == "range"
              else gy >= min(yrs) if op == "gte" else gy <= max(yrs))
        return (GateStatus.MET if ok else GateStatus.NOT_MET), gy, (
            "Your graduation year fits the stated window." if ok else
            f"The posting states graduation {op} {yrs}. Your recorded graduation year is {gy}. This is an eligibility mismatch for this vacancy.")
    if k == "VISA":
        ns = profile.needs_sponsorship
        if ns is None:
            return GateStatus.CONFIRMATION_REQUIRED, None, "The posting says visa sponsorship is unavailable. Please confirm whether you need sponsorship."
        return (GateStatus.NOT_MET if ns else GateStatus.MET), ns, (
            "The posting does not offer visa sponsorship and you indicated you need it. This cannot be fixed for this vacancy." if ns
            else "You indicated you do not need sponsorship.")
    if k == "WORK_AUTH":
        c = p["country"]
        if any(c in a.lower() or a.lower() in c for a in profile.work_authorizations):
            return GateStatus.MET, c, f"You listed work authorization for {c.title()}."
        return GateStatus.CONFIRMATION_REQUIRED, None, f"The posting requires authorization to work in {c.title()}. I could not verify this; please confirm."
    if k == "EXPERIENCE":
        need, have = p["min_years"], profile.experience_years
        if have is None:
            return GateStatus.CONFIRMATION_REQUIRED, None, f"The posting mentions {need:g}+ years of experience. Please add your experience duration."
        return (GateStatus.MET if have >= need else GateStatus.NOT_MET), have, (
            "Experience duration meets the stated minimum." if have >= need else
            f"The posting states {need:g}+ years. Your recorded experience is {have:g} years.")
    if k == "DEGREE":
        need = p["level"]
        have = degree_level(profile.degree) if profile.degree else None
        if have == need:
            return GateStatus.MET, profile.degree, "Degree level matches."
        return GateStatus.CONFIRMATION_REQUIRED, profile.degree, f"The posting mentions a {need.title()} degree. I will not assume equivalence; please confirm."
    return GateStatus.CONFIRMATION_REQUIRED, None, "Unrecognised gate."


def evaluate(requirements, profile: Profile) -> dict:
    results = []
    for r in requirements:
        for g in r.gates:
            status, have, msg = _check(g, profile)
            if status == GateStatus.NOT_MET and r.level == Level.PREFERRED:
                status = GateStatus.SOFT_MISMATCH
            elif status == GateStatus.NOT_MET and r.level == Level.UNCLEAR:
                status, msg = GateStatus.CONFIRMATION_REQUIRED, msg + " (The posting does not clearly say whether this is mandatory.)"
            results.append({"requirement_id": r.id, "kind": g.kind, "status": status.value, "required": g.params,
                            "candidate_value": have, "message": msg, "source_quote": r.span.quote})
    statuses = {x["status"] for x in results}
    overall = ("HARD_MISMATCH" if "NOT_MET" in statuses else
               "CONFIRMATION_REQUIRED" if "CONFIRMATION_REQUIRED" in statuses else "ELIGIBLE_ON_STATED_FACTS")
    return {"overall": overall, "gates": results,
            "note": "Facts are taken from the posting text and your declared profile; nothing is inferred."}
