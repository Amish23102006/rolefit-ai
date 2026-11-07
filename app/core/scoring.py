"""Transparent heuristic readiness rubric. Reproducible from documented inputs and weights."""
from datetime import date

from ..schemas import DISCLAIMER, Level, Profile
from . import evidence as ev

WEIGHTS = {"mandatory_coverage": 0.25, "preferred_coverage": 0.10, "evidence_strength": 0.20, "parsing_quality": 0.10,
           "project_relevance": 0.10, "claim_consistency": 0.10, "interview_defensibility": 0.10,
           "application_completeness": 0.05}
HARD_CAP = 35.0
PROFILE_FIELDS = ("degree", "graduation_year", "languages", "countries", "experience_years")
# How much we trust where the posting text came from (official-source explicitness).
SOURCE_TRUST = {"FETCHED_FROM_ALLOWLISTED_OFFICIAL_SOURCE": 1.0, "URL_ALLOWLISTED_CONTENT_NOT_FETCHED": 0.8,
                "USER_PROVIDED_UNVERIFIED": 0.6}


def _freshness(last_checked, today: date) -> float:
    if not last_checked:
        return 0.0
    age = (today - date.fromisoformat(last_checked)).days
    return 1.0 if age <= 7 else max(0.0, 1 - (age - 7) / 53)


def compute(requirements, evidence_items, profile: Profile, eligibility: dict, parse_quality, last_checked,
            today: date = None, source_status: str = None) -> dict:
    today = today or date.today()
    matches = ev.match(requirements, evidence_items)
    assessable = {r.id: r for r in requirements if r.skills}
    mand = [r for r in assessable.values() if r.level == Level.MANDATORY]
    pref = [r for r in assessable.values() if r.level == Level.PREFERRED]
    covered = lambda rs: [r for r in rs if matches.get(r.id)]
    used = {e["id"]: e for r in assessable for e in matches.get(r, [])}

    unknown = []
    mand_cov = len(covered(mand)) / len(mand) if mand else 0.0
    if not mand:
        unknown.append("mandatory_coverage")
    pref_cov = len(covered(pref)) / len(pref) if pref else 0.0
    if not pref:
        unknown.append("preferred_coverage")
    strengths = [max(ev.STRENGTH[e["verification_status"]] for e in matches[r.id]) for r in assessable.values() if matches.get(r.id)]
    evid = sum(strengths) / len(strengths) if strengths else 0.0
    if parse_quality is None:
        unknown.append("parsing_quality")
    proj_kinds = {"PROJECT", "WORK", "ASSESSMENT"}
    cov_all = [r for r in assessable.values() if matches.get(r.id)]
    proj = (sum(1 for r in cov_all if any(e["kind"] in proj_kinds for e in matches[r.id])) / len(assessable)) if assessable else 0.0
    conflicts = ev.detect_conflicts(profile, evidence_items)
    consistency = 1.0 if not conflicts else max(0.0, 1 - 0.5 * len(conflicts))
    defens = (sum(1 for r in cov_all if any(e["verification_status"] == "VERIFIED" or e.get("source_ref") for e in matches[r.id])) / len(cov_all)) if cov_all else 0.0
    filled = sum(1 for f in PROFILE_FIELDS if getattr(profile, f) not in (None, {}, [])) / len(PROFILE_FIELDS)

    values = {"mandatory_coverage": mand_cov, "preferred_coverage": pref_cov, "evidence_strength": evid,
              "parsing_quality": parse_quality or 0.0, "project_relevance": proj, "claim_consistency": consistency,
              "interview_defensibility": defens, "application_completeness": filled}
    dims = [{"dimension": k, "weight": WEIGHTS[k], "value": round(v, 3), "contribution": round(100 * WEIGHTS[k] * v, 2),
             "unknown": k in unknown} for k, v in values.items()]
    raw = round(sum(d["contribution"] for d in dims), 2)
    hard = eligibility["overall"] == "HARD_MISMATCH"
    score = min(raw, HARD_CAP) if hard else raw

    needs = [g for g in eligibility["gates"] if g["status"] == "CONFIRMATION_REQUIRED"]
    explicit = (sum(1 for r in requirements if r.level != Level.UNCLEAR) / len(requirements)) if requirements else 0.0
    explicit *= SOURCE_TRUST.get(source_status, 0.6)
    verif = (sum(ev.STRENGTH[e["verification_status"]] for e in used.values()) / len(used)) if used else 0.0
    fresh = _freshness(last_checked, today)
    # Confidence = quality of the inputs, never the model's or the rubric's self-belief. Unknown inputs and
    # unresolved confirmations reduce it; conflicts halve it.
    penalty = max(0.4, 1 - 0.08 * len(unknown) - 0.05 * len(needs))
    confidence = round(((explicit + verif + fresh) / 3) * penalty * (0.5 if conflicts else 1.0), 3)
    band = round((1 - confidence) * 25, 1)

    return {
        "score": score, "raw_score_before_cap": raw, "uncertainty_band": [max(0, round(score - band, 1)), min(100, round(score + band, 1))],
        "confidence": confidence,
        "label": "NOT_RECOMMENDED_ALTERNATIVE_ROUTE_REQUIRED" if hard else ("CONFIRMATION_REQUIRED" if needs else "HEURISTIC_READINESS"),
        "hard_cap_applied": hard and raw > HARD_CAP,
        "dimensions": dims, "unknowns": unknown, "conflicts": conflicts,
        "confirmations_needed": [g["message"] for g in needs],
        "uncovered_mandatory": [{"id": r.id, "text": r.text, "skills": r.skills} for r in mand if not matches.get(r.id)],
        "disclaimer": DISCLAIMER, "rubric": "heuristic; uncalibrated until real labelled outcomes exist",
    }
