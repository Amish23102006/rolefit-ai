"""Analyse-any-URL: single postings, listing pages, match report, and safety limits."""
import httpx
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.discovery.listing import job_links
from tests.conftest import PUBLIC_RESOLVER, signup

POST_A = ("<title>Machine Learning Intern</title><h2>Minimum Qualifications</h2><ul><li>Proficiency in Python and SQL</li>"
          "<li>Experience with LangChain or RAG</li><li>Graduating in 2028</li></ul><h2>Preferred</h2><ul><li>Docker</li></ul>")
POST_B = "<title>Software Engineer Intern</title><h2>Requirements</h2><ul><li>Java and Spring Boot</li><li>Data structures and algorithms</li></ul>"
LISTING = ("<title>Jobs at Example</title><h1>Open roles</h1>"
           "<a href='/careers/jobs/12345-machine-learning-intern'>ML Intern</a>"
           "<a href='https://careers.example.com/careers/jobs/67890-software-engineer-intern'>SWE Intern</a>"
           "<a href='/careers/jobs/55555-closed-role'>Closed</a>"
           "<a href='/careers/benefits'>Benefits</a><a href='https://evil.example/jobs/99999'>Elsewhere</a>"
           "<a href='/login'>Login</a>")
PAGES = {"https://careers.example.com/jobs": (200, LISTING), "https://careers.example.com/careers/jobs/12345-machine-learning-intern": (200, POST_A),
         "https://careers.example.com/careers/jobs/67890-software-engineer-intern": (200, POST_B),
         "https://careers.example.com/careers/jobs/55555-closed-role": (404, ""),
         "https://careers.example.com/js-only": (200, "<title>Careers</title><div id='app'></div><script>load()</script>")}


def make(tmp_path, domains=("*",)):
    tmp_path.mkdir(parents=True, exist_ok=True)
    calls = []

    def h(req):
        calls.append(str(req.url))
        code, html = PAGES.get(str(req.url), (404, ""))
        return httpx.Response(code, html=html)
    st = Settings(db_path=str(tmp_path / "s.db"), jwt_secret="s" * 48, allowed_job_domains=domains)
    c = TestClient(create_app(st, resolver=PUBLIC_RESOLVER, fetch_transport=httpx.MockTransport(h)))
    hd = signup(c)
    c.put("/profile", json={"graduation_year": 2028, "consents": {"job_discovery": True, "parsing": True}}, headers=hd)
    return c, hd, calls


def test_job_links_stay_on_site_and_skip_non_jobs():
    links = ["https://careers.example.com/careers/jobs/12345-ml-intern", "https://jobs.example.com/positions/98765",
             "https://evil.example/jobs/11111", "https://careers.example.com/careers/benefits",
             "https://careers.example.com/careers/jobs?page=2", "https://careers.example.com/about"]
    assert job_links(links, "https://careers.example.com/jobs") == links[:2]


def test_scan_single_posting_with_match_report(tmp_path):
    c, h, _ = make(tmp_path)
    c.post("/evidence", json={"kind": "PROJECT", "title": "p", "claim_text": "Built a Python RAG app", "skills": ["python", "rag"]}, headers=h)
    eid = c.get("/evidence", headers=h).json()[0]["id"]
    c.post(f"/evidence/{eid}/approve", headers=h)
    c.post("/documents", files={"file": ("cv.txt", b"Skills: Python, SQL, LangChain, Docker")}, headers=h)
    r = c.post("/jobs/scan", json={"url": "https://careers.example.com/careers/jobs/12345-machine-learning-intern", "company": "Ex"}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mode"] == "SINGLE_POSTING" and len(d["items"]) == 1
    m = {x["skill"]: x["status"] for x in d["items"][0]["match"]["skills"]}
    assert m["python"] == "PROVEN_BY_APPROVED_EVIDENCE" and m["rag"] == "PROVEN_BY_APPROVED_EVIDENCE"
    assert m["sql"] == "IN_CV_NOT_YET_EVIDENCED" and m["langchain"] == "IN_CV_NOT_YET_EVIDENCED"
    assert d["items"][0]["source_status"] == "FETCHED_FROM_UNVERIFIED_SITE"
    assert c.get("/jobs", headers=h).json() == []  # scanning never saves


def test_scan_listing_page_follows_job_links_and_ranks(tmp_path):
    c, h, calls = make(tmp_path)
    d = c.post("/jobs/scan", json={"url": "https://careers.example.com/jobs", "company": "Ex"}, headers=h).json()
    assert d["mode"] == "LISTING_PAGE" and {i["title"] for i in d["items"]} == {"Machine Learning Intern", "Software Engineer Intern"}
    assert d["skipped_links"] == 1  # the closed one
    assert not any("evil.example" in u or "benefits" in u or "login" in u for u in calls)
    swe = next(i for i in d["items"] if i["title"] == "Software Engineer Intern")
    assert set(swe["match"]["missing_required"]) >= {"java", "spring boot", "data structures", "algorithms"}


def test_scan_explains_javascript_pages_and_respects_allowlist_and_safety(tmp_path):
    c, h, _ = make(tmp_path)
    d = c.post("/jobs/scan", json={"url": "https://careers.example.com/js-only", "company": "Ex"}, headers=h).json()
    assert d["mode"] == "NOTHING_FOUND" and "JavaScript" in d["note"]
    assert c.post("/jobs/scan", json={"url": "http://careers.example.com/jobs", "company": "Ex"}, headers=h).status_code == 422
    c2, h2, _ = make(tmp_path / "b", domains=("boards.greenhouse.io",))
    assert c2.post("/jobs/scan", json={"url": "https://careers.example.com/jobs", "company": "Ex"}, headers=h2).status_code == 422
