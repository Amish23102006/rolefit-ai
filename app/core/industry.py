"""Industry Fit (deterministic, transparent). Ranks a curated industry table against the candidate's APPROVED
evidence skills and stated preferences. Protected characteristics are never used."""
from . import evidence as ev

INDUSTRIES = {
    "AI / ML products": {"python", "machine learning", "deep learning", "pytorch", "tensorflow", "nlp", "computer vision", "llm", "scikit-learn"},
    "Data & analytics": {"python", "sql", "pandas", "numpy", "tableau", "excel", "machine learning", "spark"},
    "Software / SaaS": {"python", "java", "javascript", "typescript", "react", "rest api", "fastapi", "django", "git", "postgresql", "docker"},
    "Cloud & DevOps": {"docker", "kubernetes", "aws", "gcp", "azure", "linux", "ci/cd", "git"},
    "Fintech": {"python", "sql", "java", "machine learning", "postgresql", "rest api"},
    "E-commerce & marketplaces": {"python", "sql", "java", "javascript", "react", "machine learning", "golang"},
    "Manufacturing & industrial AI": {"python", "computer vision", "machine learning", "deep learning", "pytorch", "linux"},
    "Consulting (technology & AI)": {"python", "sql", "excel", "tableau", "machine learning", "llm"},
}
WEIGHT_SKILLS, WEIGHT_PREF = 0.8, 0.2


def rank(profile, evidence_items: list) -> dict:
    approved = ev.usable(evidence_items)
    have = set().union(*(ev.evidence_skills(e) for e in approved)) if approved else set()
    prefs = {p.strip().lower() for p in profile.industries}
    rows = []
    for name, core in INDUSTRIES.items():
        matched = sorted(core & have)
        skill_fit = len(matched) / len(core)
        pref = 1.0 if any(p and (p in name.lower() or name.lower().split(" ")[0] in p) for p in prefs) else 0.0
        score = round(100 * (WEIGHT_SKILLS * skill_fit + WEIGHT_PREF * pref), 1)
        rows.append({"industry": name, "score": score, "skill_fit": round(skill_fit, 3), "preference_match": bool(pref),
                     "matched_skills": matched, "missing_core_skills": sorted(core - have)})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return {"ranking": rows,
            "method": f"score = 100 x ({WEIGHT_SKILLS} x share of the industry's core skills in your approved evidence + "
                      f"{WEIGHT_PREF} x stated preference). Curated table; only approved evidence counts.",
            "approved_evidence_used": len(approved),
            "note": "A heuristic guide for exploration, not a judgement of your potential."}
