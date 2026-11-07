from datetime import date

from app.core import eligibility, requirements, resume, scoring
from app.core.ats import simulate_parse
from app.schemas import Level, Profile
from app.security import injection
from app.security.redact import redact
from tests.conftest import read_fixture

JOB = read_fixture("job_ml_intern.txt")
REQS = requirements.extract_requirements(JOB)


def ev(i, kind, text, status="CANDIDATE_APPROVED", skills=(), src=None, **attrs):
    return {"id": i, "kind": kind, "title": i, "claim_text": text, "skills": list(skills), "source_ref": src,
            "attributes": attrs, "verification_status": status}


def test_levels_and_spans():
    by = {r.text: r for r in REQS}
    assert by["Proficiency in Python and SQL"].level == Level.MANDATORY
    assert by["Docker or Kubernetes experience"].level == Level.PREFERRED
    assert not any("Build Python data pipelines" in r.text for r in REQS)  # responsibilities are not requirements
    for r in REQS:
        assert JOB[r.span.start:r.span.end] == r.span.quote  # exact source span


def test_gates_detected():
    kinds = {(g.kind) for r in REQS for g in r.gates}
    assert {"GRADUATION", "LANGUAGE", "VISA"} <= kinds


def gate_status(profile, kind):
    out = eligibility.evaluate(REQS, profile)
    return {g["kind"]: g["status"] for g in out["gates"]}[kind], out["overall"]


def test_language_not_met_is_hard_mismatch():
    s, overall = gate_status(Profile(languages={"japanese": "N5"}), "LANGUAGE")
    assert s == "NOT_MET" and overall == "HARD_MISMATCH"


def test_language_met_and_unknown_never_inferred():
    assert gate_status(Profile(languages={"japanese": "N2"}), "LANGUAGE")[0] == "MET"
    assert gate_status(Profile(), "LANGUAGE")[0] == "CONFIRMATION_REQUIRED"


def test_graduation_window_and_visa():
    assert gate_status(Profile(graduation_year=2028), "GRADUATION")[0] == "MET"
    assert gate_status(Profile(graduation_year=2026), "GRADUATION")[0] == "NOT_MET"
    assert gate_status(Profile(), "GRADUATION")[0] == "CONFIRMATION_REQUIRED"
    assert gate_status(Profile(needs_sponsorship=True), "VISA")[0] == "NOT_MET"
    assert gate_status(Profile(), "VISA")[0] == "CONFIRMATION_REQUIRED"


def good_profile():
    return Profile(degree="B.Tech", graduation_year=2028, languages={"japanese": "N3"}, needs_sponsorship=False,
                   countries=["Japan"], experience_years=0.5)


EVID = [ev("e1", "PROJECT", "Built a Python and SQL pipeline processing 10k rows", skills=["python", "sql"], src="https://example.test/p"),
        ev("e2", "PROJECT", "Trained PyTorch image classifier", status="VERIFIED", skills=["pytorch"], src="https://example.test/q"),
        ev("e3", "OTHER", "Used Docker for a class assignment", status="UNVERIFIED", skills=["docker"])]


def score(profile, evidence=EVID, pq=1.0):
    elig = eligibility.evaluate(REQS, profile)
    return scoring.compute(REQS, evidence, profile, elig, pq, "2026-10-30", date(2026, 10, 31))


def test_weights_sum_to_one():
    assert abs(sum(scoring.WEIGHTS.values()) - 1.0) < 1e-9


def test_score_reproducible_and_contributions_add_up():
    a, b = score(good_profile()), score(good_profile())
    assert a == b
    assert abs(sum(d["contribution"] for d in a["dimensions"]) - a["raw_score_before_cap"]) < 0.01
    assert "not an employer ats score" in a["disclaimer"].lower()


def test_unverified_evidence_does_not_count():
    s = score(good_profile())
    assert all(m["skills"] != ["docker"] for m in s["uncovered_mandatory"])  # docker is preferred only
    pref = next(d for d in s["dimensions"] if d["dimension"] == "preferred_coverage")
    assert pref["value"] == 0.0


def test_hard_mismatch_caps_at_35():
    p = good_profile().model_copy(update={"languages": {"japanese": "N5"}})
    s = score(p)
    assert s["score"] <= 35 and s["label"] == "NOT_RECOMMENDED_ALTERNATIVE_ROUTE_REQUIRED"
    assert s["raw_score_before_cap"] > 35 and s["hard_cap_applied"]


def test_confirmation_listed_not_guessed():
    s = score(Profile())
    assert s["label"] == "CONFIRMATION_REQUIRED" and s["confirmations_needed"]


def test_conflict_surfaced_not_resolved():
    e = EVID + [ev("e4", "EDUCATION", "B.Tech CSE", skills=[], graduation_year="2027")]
    s = score(good_profile(), e)
    assert s["conflicts"] and s["conflicts"][0]["values"] == ["2028", "2027"]


def test_resume_blocks_unsupported_claims():
    ebi = {e["id"]: e for e in EVID}
    assert resume.validate_bullet("Built a Python and SQL pipeline processing 10k rows", ["e1"], ebi) == []
    assert resume.validate_bullet("Built a Python pipeline processing 50k rows", ["e1"], ebi)       # altered metric
    assert resume.validate_bullet("Built a Python pipeline using Kubernetes", ["e1"], ebi)          # unsupported skill
    assert resume.validate_bullet("Used Docker", ["e3"], ebi)                                       # unapproved evidence
    assert resume.validate_bullet("Anything", [], ebi) and resume.validate_bullet("x y z", ["nope"], ebi)


def test_draft_only_uses_approved_evidence():
    bullets = resume.build_draft(REQS, EVID)
    ids = {i for b in bullets for i in b["evidence_ids"]}
    assert "e3" not in ids and {"e1", "e2"} <= ids and not any(b["approved"] for b in bullets)


def test_injection_scan_and_context_gate():
    f = injection.scan(read_fixture("job_injection.txt"))
    assert "OVERRIDE_INSTRUCTIONS" in f and "SCORE_TAMPERING" in f
    assert injection.scan(JOB) == []
    try:
        injection.build_llm_context("job", "x", f)
        assert False
    except injection.QuarantinedContentError:
        pass
    ctx = injection.build_llm_context("job", "Mail me at a@b.co " + injection.CLOSE, [])
    assert "[EMAIL]" in ctx and ctx.count(injection.CLOSE) == 1


def test_injection_does_not_change_deterministic_parse():
    reqs = requirements.extract_requirements(read_fixture("job_injection.txt"))
    assert any("Python" in r.text for r in reqs)  # parsed as data; nothing executed or obeyed


def test_redaction():
    t = redact("Call +91 98765 43210 or a.b@x.com token=abc123 key sk-ABCDEFGHIJKLMNOPQRSTU")
    assert "98765" not in t and "a.b@x.com" not in t and "abc123" not in t and "sk-ABCDEF" not in t


def test_ats_sim_is_labelled():
    r = simulate_parse("Education\nB.Tech 2028\nSkills\nPython\nProjects\n" + "x" * 200 + " a@b.co")
    assert r["label"].startswith("SIMULATION") and r["parse_quality"] == 1.0
