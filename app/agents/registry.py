"""Honest status of the 12 product agents. All are deterministic components today; the only model call is the
optional /jobs/{id}/explain endpoint. LangGraph orchestration is a planned milestone (see README)."""

AGENTS = [
    (1, "Candidate Preference", "IMPLEMENTED", "schemas.Profile + /profile", "Structured profile, preferences and separate consents."),
    (2, "Industry Fit", "IMPLEMENTED", "core.industry + /industries/fit", "Transparent ranking over a curated industry table using approved evidence only."),
    (3, "Company Discovery", "PARTIAL", "/companies", "Candidate-curated watchlist; automatic job alerts from official Greenhouse/Lever/Ashby job-board APIs. No search-engine scraping."),
    (4, "Opportunity Verification", "IMPLEMENTED", "security.fetcher + /jobs/fetch", "Fetches allowlisted official pages with per-hop SSRF checks, size/time caps and closed-posting detection."),
    (5, "Job Requirements", "IMPLEMENTED", "core.requirements", "Deterministic extraction with source spans."),
    (6, "Candidate Evidence", "IMPLEMENTED", "core.evidence + /evidence", "Approval workflow; no automated verification of external sources."),
    (7, "Eligibility Gate", "IMPLEMENTED", "core.eligibility", "Language, graduation, visa, work auth, experience, degree."),
    (8, "ATS Simulation", "IMPLEMENTED", "core.ats", "Generic local checks only; labelled as simulation."),
    (9, "Matching & Scoring", "IMPLEMENTED", "core.scoring", "Weighted heuristic with confidence and hard cap."),
    (10, "Resume Tailoring & Integrity", "IMPLEMENTED", "core.resume", "Evidence-only bullets; export blocked until each bullet approved."),
    (11, "Gap & Learning Planner", "IMPLEMENTED", "core.gaps + /jobs/{id}/gaps", "Deadline-aware plan with fixable/non-fixable categories and official-docs links; proof gate."),
    (12, "Assessment & Interview Readiness", "IMPLEMENTED", "core.practice + /jobs/{id}/practice + /applications",
     "Original practice questions; refuses during a live assessment; application tracker records outcomes."),
]


def describe():
    return [dict(zip(("number", "name", "status", "component", "notes"), a)) for a in AGENTS]
