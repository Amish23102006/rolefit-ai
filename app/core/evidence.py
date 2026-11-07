"""Evidence graph helpers: only candidate-approved/verified evidence may support any claim."""
from ..schemas import Level, Verification
from .skills import find_skills, normalize

USABLE = {Verification.CANDIDATE_APPROVED.value, Verification.VERIFIED.value}
STRENGTH = {Verification.VERIFIED.value: 1.0, Verification.CANDIDATE_APPROVED.value: 0.6}


def usable(evidence: list) -> list:
    return [e for e in evidence if e["verification_status"] in USABLE]


def evidence_skills(e: dict) -> set:
    return {normalize(s) for s in e.get("skills", [])} | find_skills(e["claim_text"])


def match(requirements, evidence: list) -> dict:
    """requirement id -> list of usable evidence supporting at least one of its skills."""
    ev = usable(evidence)
    out = {}
    for r in requirements:
        if not r.skills:
            continue
        need = set(r.skills)
        out[r.id] = [e for e in ev if need & evidence_skills(e)]
    return out


def detect_conflicts(profile, evidence: list) -> list:
    conflicts = []
    for e in evidence:
        gy = e.get("attributes", {}).get("graduation_year")
        if gy and profile.graduation_year and str(profile.graduation_year) != str(gy):
            conflicts.append({"field": "graduation_year", "values": [str(profile.graduation_year), str(gy)],
                              "sources": ["profile", e["id"]],
                              "message": "Profile and evidence disagree on graduation year. Please correct one; I have not chosen for you."})
    return conflicts
