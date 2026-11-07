"""Generic local parsing diagnostics. This is a SIMULATION, never an employer ATS score."""
import re

LABEL = ("SIMULATION: generic local parsing checks only. It does not represent Workday, Greenhouse, Lever, "
         "SAP SuccessFactors or any employer's private settings.")


def simulate_parse(text: str) -> dict:
    t = text or ""
    checks = {
        "has_email_or_contact": bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", t)) or "[EMAIL]" in t,
        "has_education_section": bool(re.search(r"^\W*education\b", t, re.I | re.M)),
        "has_skills_section": bool(re.search(r"^\W*(technical )?skills\b", t, re.I | re.M)),
        "has_projects_or_experience": bool(re.search(r"^\W*(projects?|experience|work experience)\b", t, re.I | re.M)),
        "sufficient_length": len(t.strip()) >= 200,
        "no_icon_font_glyphs": not re.search("[\ue000-\uf8ff]", t),
        "dates_detected": bool(re.search(r"\b(19|20)\d{2}\b", t)),
    }
    issues = [f"Check failed: {k}" for k, v in checks.items() if not v]
    return {"label": LABEL, "parse_quality": sum(checks.values()) / len(checks), "checks": checks, "issues": issues,
            "unknowns": ["Employer ATS configuration", "Vendor-specific parsing behaviour"]}
