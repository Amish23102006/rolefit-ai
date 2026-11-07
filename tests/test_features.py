"""Tests for the v0.2 features: official-page fetching, gap planner, practice, industry fit, companies,
application tracking, list/delete endpoints and .env handling."""
from datetime import date

import httpx
import pytest

from app.config import Settings
from app.core import gaps, practice
from app.core.requirements import extract_requirements
from app.security.fetcher import FetchError, fetch_official_page, html_to_text
from tests.conftest import PUBLIC_RESOLVER, read_fixture, signup

GOOD = {"degree": "B.Tech", "graduation_year": 2028, "languages": {"japanese": "N3"}, "needs_sponsorship": False,
        "countries": ["Japan"], "experience_years": 0.5, "industries": ["AI / ML products"],
        "consents": {"parsing": True, "job_discovery": True}}
JOB = {"title": "ML Intern", "company": "Synthetic Co", "description_text": read_fixture("job_ml_intern.txt"), "last_checked": "2026-10-30"}
POSTING_HTML = ("<html><head><title>ML Intern - Synthetic Co</title><script>alert('x')</script></head><body>"
                "<h2>Minimum Qualifications</h2><ul><li>Proficiency in Python and SQL</li>"
                "<li>Graduating in 2028</li></ul><h2>Preferred Qualifications</h2><ul><li>Docker experience</li></ul></body></html>")
ALLOWED = ("boards.greenhouse.io", "jobs.lever.co")


def ev(c, h, claim, skills, approve=True, **kw):
    e = c.post("/evidence", json={"kind": "PROJECT", "title": "p", "claim_text": claim, "skills": skills,
                                  "source_ref": "https://example.test/p"} | kw, headers=h).json()
    if approve:
        c.post(f"/evidence/{e['id']}/approve", headers=h)
    return e["id"]


def transport(routes):
    def handler(req):
        return routes[str(req.url)]() if callable(routes[str(req.url)]) else routes[str(req.url)]
    return httpx.MockTransport(handler)


# ---------------- fetcher ----------------
def test_html_to_text_drops_scripts_and_keeps_structure():
    text, title = html_to_text(POSTING_HTML)
    assert "alert" not in text and title == "ML Intern - Synthetic Co"
    assert "- Proficiency in Python and SQL" in text and "Minimum Qualifications" in text


def test_fetch_follows_safe_redirect_and_revalidates_each_hop():
    t = transport({
        "https://boards.greenhouse.io/synth/jobs/1": httpx.Response(302, headers={"location": "https://boards.greenhouse.io/synth/jobs/2"}),
        "https://boards.greenhouse.io/synth/jobs/2": httpx.Response(200, html=POSTING_HTML),
    })
    r = fetch_official_page("https://boards.greenhouse.io/synth/jobs/1", ALLOWED, True, PUBLIC_RESOLVER, t)
    assert r.status == "OPEN_ON_OFFICIAL_SOURCE" and r.final_url.endswith("/jobs/2") and len(r.sha256) == 64


@pytest.mark.parametrize("location", ["https://evil.example/x", "http://boards.greenhouse.io/x", "https://169.254.169.254/latest"])
def test_fetch_blocks_unsafe_redirects(location):
    t = transport({"https://boards.greenhouse.io/a": httpx.Response(302, headers={"location": location})})
    with pytest.raises(FetchError, match="after redirect"):
        fetch_official_page("https://boards.greenhouse.io/a", ALLOWED, True, PUBLIC_RESOLVER, t)


def test_fetch_blocks_private_dns_and_redirect_loops_and_big_pages():
    with pytest.raises(FetchError):
        fetch_official_page("https://boards.greenhouse.io/a", ALLOWED, True, lambda h, p: ["10.0.0.5"], transport({}))
    loop = transport({"https://boards.greenhouse.io/a": httpx.Response(302, headers={"location": "/a"})})
    with pytest.raises(FetchError, match="Too many redirects"):
        fetch_official_page("https://boards.greenhouse.io/a", ALLOWED, True, PUBLIC_RESOLVER, loop)
    big = transport({"https://boards.greenhouse.io/a": httpx.Response(200, html="x" * 5000)})
    with pytest.raises(FetchError, match="too large"):
        fetch_official_page("https://boards.greenhouse.io/a", ALLOWED, True, PUBLIC_RESOLVER, big, max_bytes=1000)
    pdf = transport({"https://boards.greenhouse.io/a": httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})})
    with pytest.raises(FetchError, match="not an HTML"):
        fetch_official_page("https://boards.greenhouse.io/a", ALLOWED, True, PUBLIC_RESOLVER, pdf)


def test_fetch_detects_closed_postings():
    t = transport({"https://jobs.lever.co/x/1": httpx.Response(200, html="<p>This job is no longer accepting applications.</p>"),
                   "https://jobs.lever.co/x/2": httpx.Response(404, html="gone")})
    assert fetch_official_page("https://jobs.lever.co/x/1", ALLOWED, True, PUBLIC_RESOLVER, t).status == "CLOSED_OR_UNAVAILABLE"
    assert fetch_official_page("https://jobs.lever.co/x/2", ALLOWED, True, PUBLIC_RESOLVER, t).status == "CLOSED_OR_UNAVAILABLE"


def test_jobs_fetch_endpoint(make_client, tmp_path):
    from app.api import create_app
    from fastapi.testclient import TestClient
    t = transport({"https://boards.greenhouse.io/synth/jobs/9": httpx.Response(200, html=POSTING_HTML),
                   "https://boards.greenhouse.io/synth/jobs/closed": httpx.Response(410, html="")})
    c = TestClient(create_app(Settings(db_path=str(tmp_path / "f.db"), jwt_secret="s" * 48), resolver=PUBLIC_RESOLVER, fetch_transport=t))
    h = signup(c)
    body = {"url": "https://boards.greenhouse.io/synth/jobs/9", "company": "Synthetic Co"}
    assert c.post("/jobs/fetch", json=body, headers=h).status_code == 403  # needs job_discovery consent
    c.put("/profile", json=GOOD, headers=h)
    r = c.post("/jobs/fetch", json=body, headers=h)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["verification_status"] == "FETCHED_FROM_ALLOWLISTED_OFFICIAL_SOURCE" and d["title"] == "ML Intern - Synthetic Co"
    assert any("sql" in q["skills"] for q in d["requirements"])
    job = c.get(f"/jobs/{d['id']}", headers=h).json()
    assert len(job["content_sha256"]) == 64 and job["last_checked"] == date.today().isoformat()
    closed = c.post("/jobs/fetch", json=body | {"url": "https://boards.greenhouse.io/synth/jobs/closed"}, headers=h)
    assert closed.status_code == 409
    assert c.post("/jobs/fetch", json=body | {"url": "https://evil.example/x"}, headers=h).status_code == 422


# ---------------- gap planner ----------------
def test_gap_plan_categories_and_deadline():
    reqs = extract_requirements(read_fixture("job_ml_intern.txt"))
    evidence = [{"id": "e1", "kind": "PROJECT", "claim_text": "Built a Python tool", "skills": ["python"], "verification_status": "CANDIDATE_APPROVED"},
                {"id": "e2", "kind": "PROJECT", "claim_text": "Trained a PyTorch model", "skills": ["pytorch"], "verification_status": "UNVERIFIED"}]
    from app.core import eligibility
    from app.schemas import Profile
    prof = Profile(graduation_year=2030, needs_sponsorship=True, languages={"japanese": "N5"})
    out = gaps.plan(reqs, evidence, eligibility.evaluate(reqs, prof), "2026-11-10", today=date(2026, 11, 5))
    cats = {(i["category"], i["topic"]) for i in out["items"]}
    assert ("NOT_FIXABLE_FOR_THIS_VACANCY", "VISA") in cats and ("NOT_FIXABLE_FOR_THIS_VACANCY", "GRADUATION") in cats
    assert ("LONG_TERM", "LANGUAGE") in cats
    assert ("OMITTED_EVIDENCE", "pytorch") in cats  # unapproved evidence surfaced, never auto-approved
    assert ("SHORT_TERM_FIXABLE", "sql") in cats and ("SHORT_TERM_FIXABLE", "docker") in cats
    assert not any(i["topic"] == "python" for i in out["items"])  # covered by approved evidence
    sql = next(i for i in out["items"] if i["topic"] == "sql")
    assert sql["feasibility"] == "FITS_BEFORE_DEADLINE" and sql["learn_link"].startswith("https://www.postgresql.org/")
    assert out["days_left"] == 5 and out["items"][0]["category"] == "NOT_FIXABLE_FOR_THIS_VACANCY"


def test_gaps_endpoint_is_owner_scoped(client):
    a, b = signup(client, "a@example.test"), signup(client, "b@example.test")
    client.put("/profile", json=GOOD, headers=a)
    jid = client.post("/jobs", json=JOB, headers=a).json()["id"]
    r = client.post(f"/jobs/{jid}/gaps", json={"deadline": "2030-01-01"}, headers=a)
    assert r.status_code == 200 and r.json()["summary"]["SHORT_TERM_FIXABLE"] >= 1
    assert client.post(f"/jobs/{jid}/gaps", json={}, headers=b).status_code == 404


# ---------------- practice ----------------
def test_practice_is_original_relevant_and_refuses_live_assessment(client):
    h = signup(client)
    client.put("/profile", json=GOOD, headers=h)
    ev(client, h, "Built a Python and SQL pipeline processing 10k rows", ["python", "sql"])
    jid = client.post("/jobs", json=JOB, headers=h).json()["id"]
    r = client.post(f"/jobs/{jid}/practice", json={"mode": "mixed", "count": 20}, headers=h)
    assert r.status_code == 200
    qs = r.json()["questions"]
    types = {q["type"] for q in qs}
    assert {"TECHNICAL", "PROJECT_DEEP_DIVE", "BEHAVIOURAL", "JAPAN_SPECIFIC"} <= types
    assert all(q["source"] in ("RoleFit original template bank", "Your approved evidence") for q in qs)
    assert any(q.get("skill") == "sql" for q in qs)
    live = client.post(f"/jobs/{jid}/practice", json={"live_assessment_active": True}, headers=h)
    assert live.status_code == 409


def test_practice_is_reproducible_for_same_seed():
    reqs = extract_requirements(read_fixture("job_ml_intern.txt"))
    a = practice.generate({"title": "x"}, reqs, [], "technical", 5, "seed")
    b = practice.generate({"title": "x"}, reqs, [], "technical", 5, "seed")
    assert a == b and len(a["questions"]) == 5


# ---------------- industry fit, companies ----------------
def test_industry_fit_uses_only_approved_evidence(client):
    h = signup(client)
    client.put("/profile", json=GOOD, headers=h)
    assert client.get("/industries/fit", headers=h).json()["approved_evidence_used"] == 0
    ev(client, h, "Trained a PyTorch NLP model in Python", ["python", "pytorch", "nlp"])
    ev(client, h, "Unapproved Kubernetes claim", ["kubernetes"], approve=False)
    r = client.get("/industries/fit", headers=h).json()
    top = r["ranking"][0]
    assert top["industry"] == "AI / ML products" and top["preference_match"] and "pytorch" in top["matched_skills"]
    devops = next(x for x in r["ranking"] if x["industry"] == "Cloud & DevOps")
    assert "kubernetes" not in devops["matched_skills"]


def test_companies_watchlist(client):
    h = signup(client)
    r = client.post("/companies", json={"name": "Synthetic Co", "careers_url": "https://boards.greenhouse.io/synth"}, headers=h)
    assert r.status_code == 201 and r.json()["fetch_allowed"]
    r = client.post("/companies", json={"name": "Other", "careers_url": "https://careers.other.example"}, headers=h)
    assert r.status_code == 201 and not r.json()["fetch_allowed"] and "fetch_note" in r.json()
    assert client.post("/companies", json={"name": "Bad", "careers_url": "http://insecure.example"}, headers=h).status_code == 422
    cid = r.json()["id"]
    assert len(client.get("/companies", headers=h).json()) == 2
    other = signup(client, "o@example.test")
    assert client.delete(f"/companies/{cid}", headers=other).status_code == 404
    assert client.delete(f"/companies/{cid}", headers=h).status_code == 200


# ---------------- applications / outcomes ----------------
def test_application_tracking_and_outcomes(client):
    a, b = signup(client, "a@example.test"), signup(client, "b@example.test")
    client.put("/profile", json=GOOD, headers=a)
    jid = client.post("/jobs", json=JOB, headers=a).json()["id"]
    assert client.post("/applications", json={"job_id": jid}, headers=b).status_code == 404  # B cannot track A's job
    app_ = client.post("/applications", json={"job_id": jid, "deadline": "2026-12-01", "next_action": "Submit"}, headers=a).json()
    assert app_["stage"] == "PLANNED" and app_["company"] == "Synthetic Co"
    for stage in ("APPLIED", "ONLINE_TEST", "REJECTED"):
        assert client.patch(f"/applications/{app_['id']}", json={"stage": stage}, headers=a).status_code == 200
    assert client.patch(f"/applications/{app_['id']}", json={"stage": "OFFER"}, headers=b).status_code == 404
    o = client.get("/applications/outcomes", headers=a).json()
    assert o["ever_reached"]["ONLINE_TEST"] == 1 and o["current_stage_counts"]["REJECTED"] == 1 and "Not enough" in o["calibration"]
    assert [h["stage"] for h in client.get("/applications", headers=a).json()[0]["history"]] == ["PLANNED", "APPLIED", "ONLINE_TEST", "REJECTED"]


# ---------------- list / get / delete ----------------
def test_list_get_delete_are_owner_scoped(client):
    a, b = signup(client, "a@example.test"), signup(client, "b@example.test")
    client.put("/profile", json=GOOD, headers=a)
    eid = ev(client, a, "Built a Python and SQL pipeline processing 10k rows", ["python", "sql"])
    jid = client.post("/jobs", json=JOB, headers=a).json()["id"]
    cv = client.post(f"/jobs/{jid}/resumes", json={"acknowledge_mismatch": True}, headers=a).json()
    doc = client.post("/documents", files={"file": ("cv.txt", b"Education\n2028")}, headers=a).json()["id"]
    assert [j["id"] for j in client.get("/jobs", headers=a).json()] == [jid] and client.get("/jobs", headers=b).json() == []
    assert client.get(f"/jobs/{jid}", headers=b).status_code == 404
    assert client.get(f"/resumes?job_id={jid}", headers=a).json()[0]["id"] == cv["id"]
    assert client.get(f"/resumes/{cv['id']}", headers=b).status_code == 404
    for path in (f"/jobs/{jid}", f"/evidence/{eid}", f"/documents/{doc}"):
        assert client.delete(path, headers=b).status_code == 404
    assert client.delete(f"/evidence/{eid}", headers=a).status_code == 200
    assert client.delete(f"/documents/{doc}", headers=a).status_code == 200
    assert client.delete(f"/jobs/{jid}", headers=a).status_code == 200
    assert client.get("/jobs", headers=a).json() == [] and client.get("/resumes", headers=a).json() == []  # cascade


# ---------------- config ----------------
def test_placeholder_jwt_secret_is_refused(monkeypatch):
    monkeypatch.setenv("ROLEFIT_JWT_SECRET", "change-me-to-a-random-string-of-at-least-32-characters")
    with pytest.raises(RuntimeError, match="placeholder"):
        Settings.from_env(load_env_file=False)


def test_env_file_loaded_without_overriding_real_env(tmp_path, monkeypatch):
    from app import config
    env = tmp_path / ".env"
    env.write_text("ROLEFIT_LLM_MODEL=from-file\nROLEFIT_DB_PATH=from-file.db\n")
    monkeypatch.setenv("ROLEFIT_LLM_MODEL", "tmp")
    monkeypatch.delenv("ROLEFIT_LLM_MODEL")  # registered with monkeypatch, so the value loaded from the file is undone
    monkeypatch.setenv("ROLEFIT_DB_PATH", "from-env.db")
    monkeypatch.delenv("ROLEFIT_JWT_SECRET", raising=False)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    assert config.load_dotenv_file(env)
    s = Settings.from_env(load_env_file=False)
    assert s.llm_model == "from-file" and s.db_path == "from-env.db"


def test_confidence_reflects_source_trust_and_unknowns():
    from app.core import eligibility, scoring
    from app.schemas import Profile
    reqs = extract_requirements(read_fixture("job_ml_intern.txt"))
    evid = [{"id": "e1", "kind": "PROJECT", "claim_text": "Built a Python and SQL tool", "skills": ["python", "sql"],
             "verification_status": "VERIFIED", "source_ref": "https://example.test"}]
    prof = Profile(graduation_year=2028, needs_sponsorship=False, languages={"japanese": "N3"})
    el = eligibility.evaluate(reqs, prof)
    today = date(2026, 11, 5)
    pasted = scoring.compute(reqs, evid, prof, el, None, "2026-11-05", today, "USER_PROVIDED_UNVERIFIED")
    fetched = scoring.compute(reqs, evid, prof, el, 0.9, "2026-11-05", today, "FETCHED_FROM_ALLOWLISTED_OFFICIAL_SOURCE")
    assert pasted["confidence"] < fetched["confidence"] <= 1.0
    assert pasted["uncertainty_band"][1] - pasted["uncertainty_band"][0] > 0
