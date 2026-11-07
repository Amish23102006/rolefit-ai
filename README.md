# RoleFit AI Career Navigator

Evidence-grounded, privacy-preserving career-preparation platform: FastAPI backend + Streamlit UI.
**Not an employer ATS score and not a guarantee of selection.**
Built from *RoleFit AI Secure End-to-End Blueprint & Master Prompt*.

## Quick start (macOS / Linux)
```bash
./scripts/setup.sh   # creates .venv, installs everything, creates .env with a random JWT secret, runs the tests
./run.sh             # starts the API (http://127.0.0.1:8000/docs) and the UI (http://127.0.0.1:8501)
```
Ctrl+C stops both. In VS Code you can also use **Run and Debug → "RoleFit API + UI"**.

Windows (PowerShell): `python -m venv .venv; .venv\Scripts\activate; pip install -r requirements-dev.txt`,
copy `.env.example` to `.env` and set `ROLEFIT_JWT_SECRET` (`python -c "import secrets; print(secrets.token_urlsafe(48))"`),
then run `uvicorn app.main:app` and, in a second terminal, `streamlit run ui/app.py`.

Docker: `docker compose up --build` (API on 8000, UI on 8501, both bound to 127.0.0.1).

`.env` is loaded automatically from the project root; real environment variables always win.
The API refuses to start with the placeholder secret from `.env.example`.

## Automatic job alerts
1. **Profile**: set target roles (e.g. `machine learning, data scientist, software engineer`), preferred countries, keep
   "internships, graduate and entry-level only" ticked, and turn on the **Job discovery** consent.
2. **Industries & companies**: follow companies by pasting their official careers URL on Greenhouse
   (`boards.greenhouse.io/<name>`), Lever (`jobs.lever.co/<name>`) or Ashby (`jobs.ashbyhq.com/<name>`).
3. That's it. The API checks those boards every `ROLEFIT_DISCOVERY_INTERVAL_HOURS` (default 6) while it runs, keeps postings that
   match your roles, level and countries, runs the eligibility gate and readiness score on each, and shows them on **Job alerts**.
   **Save** turns an alert into a normal job for analysis, gap plan, resume and practice.

### Openings from any website: Google Alerts
On **Job alerts → Google Alerts feeds**: create an alert at google.com/alerts (e.g. `"machine learning intern" India 2027`),
choose **Deliver to: RSS feed**, and paste the feed link. Matching results appear as *leads* (snippet + link). Open the link and
paste or fetch the full posting to analyse it.

### Email me new alerts
Tick **Email me when new job alerts are found** on the Profile page and add to `.env` (Gmail example: turn on 2-Step
Verification, then create an App Password at https://myaccount.google.com/apppasswords):
```
ROLEFIT_SMTP_HOST=smtp.gmail.com
ROLEFIT_SMTP_PORT=587
ROLEFIT_SMTP_USER=you@gmail.com
ROLEFIT_SMTP_PASSWORD=<16-character app password>
```
Emails contain only titles, companies, locations, links and scores, and go to your RoleFit account email.

Sources are the platforms' documented public job-board APIs and your own Google Alerts feeds only. RoleFit does not scrape Google or any search engine, never
logs in anywhere, and fetches each board at most once per cycle no matter how many users follow it. Companies that use other
career systems (Workday, SuccessFactors, their own site) cannot be followed automatically; paste or fetch those postings instead.

## What the app does (UI pages)
0. **Job alerts** – matching postings from the companies you follow, with eligibility and readiness, checked automatically.
1. **Profile & consent** – degree, graduation year, languages, visa, preferences; five separate consents (all off by default); resume upload for parsing diagnostics.
2. **Evidence** – add claims with proof links; nothing counts until you approve it; VERIFIED needs a source.
3. **Jobs** – paste a posting, or fetch it from an allowlisted official URL; requirements are extracted deterministically with source quotes.
4. **Analysis** – eligibility gate, transparent readiness score with confidence and range, optional plain-language AI explanation.
5. **Gap plan** – not fixable / needs confirmation / unapproved evidence / short-term / long-term, with deadline feasibility and official-docs links.
6. **Resume** – evidence-only bullets; edits are validated; export is blocked until every bullet is approved.
7. **Practice** – original technical, project deep-dive, behavioural and Japan-specific questions; disabled during a live assessment.
8. **Applications** – track stage, deadline, next action and outcome history.
9. **Industries & companies** – transparent industry-fit ranking and a personal company watchlist.
10. **Privacy** – full JSON export, activity log, re-authenticated deletion.

## Status of the 12 agents (`GET /agents`)
| # | Agent | Status |
|---|---|---|
| 1 | Candidate Preference | Implemented |
| 2 | Industry Fit | Implemented (curated table, approved evidence only) |
| 3 | Company Discovery | Partial – candidate-curated watchlist + automatic alerts from official Greenhouse/Lever/Ashby APIs; no crawling by design |
| 4 | Opportunity Verification | Implemented – allowlisted fetch, per-hop SSRF checks, closed-posting detection |
| 5 | Job Requirements | Implemented |
| 6 | Candidate Evidence | Implemented |
| 7 | Eligibility Gate | Implemented |
| 8 | ATS Simulation | Implemented (generic, labelled simulation) |
| 9 | Matching & Scoring | Implemented |
| 10 | Resume Tailoring & Integrity | Implemented |
| 11 | Gap & Learning Planner | Implemented |
| 12 | Assessment & Interview Readiness | Implemented (+ application tracker) |

All agents are deterministic. The only model call is the optional `POST /jobs/{id}/explain`. LangGraph orchestration is not used yet.

## API flow
`/auth/register` → `/auth/login` → `PUT /profile` → `POST /evidence` + `/evidence/{id}/approve` → `POST /jobs` or `POST /jobs/fetch`
→ `GET /jobs/{id}/eligibility` → `POST /jobs/{id}/score` → `POST /jobs/{id}/gaps` → `POST /jobs/{id}/resumes`
→ `/resumes/{id}/bullets/{bid}/approve` → `GET /resumes/{id}/export` → `POST /jobs/{id}/practice` → `POST /applications`.
Full interactive docs at `/docs`.

## Rules baked into the code
Untrusted text is data; missing facts return `CONFIRMATION_REQUIRED`; conflicts are shown, never resolved; every CV bullet must cite
approved evidence and may not add numbers or skills absent from it; nothing is exported without per-bullet approval; practice is
refused while a live assessment is in progress; every user-owned record is owner-scoped (404 on someone else's id); synthetic data only.

## Analyse any job URL
**Jobs → Analyse any URL** accepts any public https link. A single posting is analysed directly; a careers or search
page is scanned for up to 10 job links on the same site, and each is analysed. For every job you get eligibility,
readiness and a skill table: ✅ proven by approved evidence, 🟡 in your uploaded CV but not yet evidenced, ❌ missing,
plus the required skills to build next. Nothing is saved until you press **Save this job**. Pages that build their job
lists with JavaScript cannot be read (RoleFit never runs page scripts); paste those postings instead.

## Fetching official postings
Add the official career domains you trust to `ROLEFIT_ALLOWED_JOB_DOMAINS` (default: Greenhouse and Lever boards), tick the
"Job discovery" consent, then use **Jobs → Fetch from an official URL**. Only https, public-IP, allowlisted hosts are fetched;
redirects are re-checked (max 3); pages over 2 MB, non-HTML content and closed postings are rejected.

## Free LLM setup (optional)
1. Create a free key at https://console.groq.com/keys (no card).
2. In `.env`: `ROLEFIT_LLM_PROVIDER=groq`, `ROLEFIT_LLM_API_KEY=<your key>`. Never commit `.env`.
3. Default model is `openai/gpt-oss-120b` (Groq retired `llama-3.3-70b-versatile`). Check the Groq console if it changes.
4. Tick "LLM processing" consent, then press **Explain in plain language** on the Analysis page.
For maximum privacy use `ollama` locally.

## Tests
`pytest -q` – 91 tests: auth, isolation, uploads, SSRF, fetch redirects, job-board connectors and alerts, injection, scoring, eligibility, gaps, practice integrity,
applications, LLM gateway (mocked), config.

## Docs
`docs/THREAT_MODEL.md` lists threats, controls, the test proving each, and residual risks. Read the residual-risk list before any real use.

*This is a technical design, not legal advice. Obtain privacy/security/legal review before any multi-user deployment.*
