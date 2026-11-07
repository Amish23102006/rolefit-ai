"""RoleFit AI - Streamlit UI. A thin client: every rule (auth, authorization, scoring, approvals) is enforced by the API.
Set API_URL in Streamlit secrets (cloud) or the environment (local). Default: http://127.0.0.1:8000"""
import json
import os
from datetime import date

import httpx
import streamlit as st

st.set_page_config(page_title="RoleFit AI", page_icon="🧭", layout="wide")


def _api_url() -> str:
    try:
        if "API_URL" in st.secrets:
            return str(st.secrets["API_URL"])
    except Exception:
        pass
    return os.getenv("API_URL", "http://127.0.0.1:8000")


API = _api_url().rstrip("/")
S = st.session_state
STAGES = ["PLANNED", "APPLIED", "ONLINE_TEST", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"]


def api(method, path, body=None, files=None, params=None):
    headers = {"Authorization": f"Bearer {S['token']}"} if S.get("token") else {}
    try:
        r = httpx.request(method, API + path, json=body, files=files, params=params, headers=headers, timeout=90)
    except httpx.TimeoutException:
        return 0, {"detail": "The server may be waking up (free hosting sleeps when idle). Please try again in a minute."}
    except httpx.HTTPError:
        return 0, {"detail": f"Could not reach the API at {API}. Is it running? Start it with ./run.sh (or uvicorn app.main:app)."}
    if r.status_code == 401 and S.get("token"):
        S.pop("token", None)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"detail": r.text[:200]}


def err(code, data):
    d = data.get("detail", data) if isinstance(data, dict) else data
    if isinstance(d, list):
        d = "; ".join(f"{'.'.join(map(str, x.get('loc', [])[1:]))}: {x.get('msg')}" for x in d)
    elif isinstance(d, dict):
        extra = d.get("errors") or [p for x in d.get("problems", []) for p in x.get("errors", [])]
        d = d.get("message", json.dumps(d)) + (f" ({'; '.join(map(str, extra))})" if extra else "")
    st.error(f"{code or 'Error'}: {d}")


def ok(c, d, msg=None, rerun=False):
    if 200 <= c < 300:
        if msg:
            st.success(msg)
        if rerun:
            st.rerun()
        return True
    err(c, d)
    return False


def csv(s):
    return [x.strip() for x in s.split(",") if x.strip()]


def job_picker(key="job"):
    c, jobs = api("GET", "/jobs")
    if c != 200:
        err(c, jobs)
        return None
    if not jobs:
        st.info("Add a job on the **Jobs** page first.")
        return None
    ids = [j["id"] for j in jobs]
    cur = S.get("job_id") if S.get("job_id") in ids else ids[-1]
    jid = st.selectbox("Job", ids, index=ids.index(cur), key=f"pick_{key}",
                       format_func=lambda i: next(f"{j['title']} - {j['company']}" for j in jobs if j["id"] == i))
    S["job_id"] = jid
    return jid


# ---------------------------------------------------------------- auth
def auth_page():
    st.info("Use **synthetic or non-sensitive data** in demos. Your data stays in the API's database until you delete it.")
    t1, t2 = st.tabs(["Sign in", "Create account"])
    with t1:
        with st.form("login"):
            e = st.text_input("Email")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in"):
                c, d = api("POST", "/auth/login", {"email": e, "password": p})
                if c == 200:
                    S["token"] = d["access_token"]
                    st.rerun()
                err(c, d)
    with t2:
        with st.form("register"):
            e = st.text_input("Email")
            p = st.text_input("Password (12+ characters)", type="password")
            if st.form_submit_button("Create account"):
                c, d = api("POST", "/auth/register", {"email": e, "password": p})
                ok(c, d, "Account created. Please sign in.")


# ---------------------------------------------------------------- profile
def profile_page():
    st.header("1. Profile & consent")
    c, p = api("GET", "/profile")
    if c != 200:
        return err(c, p)
    langs = ", ".join(f"{k}={v}" for k, v in p["languages"].items())
    with st.form("profile"):
        col = st.columns(2)
        degree = col[0].text_input("Degree (e.g. B.Tech)", p["degree"] or "")
        field = col[1].text_input("Field of study", p["field_of_study"] or "")
        gy = col[0].text_input("Graduation year (blank = unknown)", str(p["graduation_year"] or ""))
        exp = col[1].text_input("Experience in years (blank = unknown)", "" if p["experience_years"] is None else str(p["experience_years"]))
        lang = st.text_input("Languages, self-declared (e.g. japanese=N5, english=C1)", langs)
        wa = st.text_input("Work authorizations (comma-separated countries)", ", ".join(p["work_authorizations"]))
        sp = st.selectbox("Do you need visa sponsorship?", ["Unknown", "Yes", "No"],
                          index={None: 0, True: 1, False: 2}[p["needs_sponsorship"]])
        countries = st.text_input("Preferred countries", ", ".join(p["countries"]))
        inds = st.text_input("Preferred industries (e.g. AI / ML products, Data & analytics)", ", ".join(p["industries"]))
        roles = st.text_input("Target roles for job alerts (e.g. machine learning, data scientist, software engineer)",
                              ", ".join(p.get("target_roles", [])))
        early = st.checkbox("Alerts: internships, graduate and entry-level roles only", p.get("early_career_only", True))
        mail = st.checkbox("Email me when new job alerts are found", p.get("email_alerts", False))
        ret = st.number_input("Keep my data for (days)", 1, 3650, p["retention_days"])
        st.markdown("**Consents** (each is separate; all off by default)")
        cs = p["consents"]
        c1 = st.checkbox("Parse documents I upload", cs["parsing"])
        c2 = st.checkbox("Job discovery (fetch official job pages I choose)", cs["job_discovery"])
        c3 = st.checkbox("Use an AI model to explain my results (LLM processing)", cs["llm_processing"])
        c4 = st.checkbox("Aggregated analytics", cs["analytics"])
        c5 = st.checkbox("Use my data to improve models (not recommended)", cs["model_improvement"])
        if st.form_submit_button("Save profile"):
            try:
                body = {"degree": degree or None, "field_of_study": field or None,
                        "graduation_year": int(gy) if gy.strip() else None,
                        "experience_years": float(exp) if exp.strip() else None,
                        "languages": {k.strip().lower(): v.strip().upper() for k, v in (x.split("=", 1) for x in csv(lang))},
                        "work_authorizations": csv(wa), "needs_sponsorship": {"Unknown": None, "Yes": True, "No": False}[sp],
                        "countries": csv(countries), "industries": csv(inds), "target_roles": [r.lower() for r in csv(roles)],
                        "early_career_only": early, "email_alerts": mail, "retention_days": int(ret),
                        "consents": {"parsing": c1, "job_discovery": c2, "llm_processing": c3, "analytics": c4, "model_improvement": c5}}
            except ValueError:
                return st.error("Please check the number fields and the languages format (name=level).")
            c, d = api("PUT", "/profile", body)
            ok(c, d, "Saved.")
    st.subheader("Resumes for parsing diagnostics")
    f = st.file_uploader("PDF, DOCX or TXT (max 5 MB)", type=["pdf", "docx", "txt"])
    if f and st.button("Upload"):
        c, d = api("POST", "/documents", files={"file": (f.name, f.getvalue())})
        if ok(c, d, f"Uploaded {d.get('filename')}."):
            if d["quarantined"]:
                st.warning(f"Flagged and quarantined (kept out of any AI prompt): {', '.join(d['findings'])}")
    c, docs = api("GET", "/documents")
    for d in docs if c == 200 else []:
        col = st.columns([5, 1])
        col[0].write(f"📄 {d['filename']} ({d['size']} bytes)" + (" - ⚠️ quarantined" if d["quarantined"] else ""))
        if col[1].button("Delete", key=f"dd{d['id']}"):
            c2_, r = api("DELETE", f"/documents/{d['id']}")
            ok(c2_, r, rerun=True)


# ---------------------------------------------------------------- evidence
def evidence_page():
    st.header("2. Evidence")
    st.caption("Only evidence you approve can appear on a CV or count toward your score.")
    with st.form("ev", clear_on_submit=True):
        kind = st.selectbox("Type", ["PROJECT", "EDUCATION", "WORK", "CERTIFICATE", "ASSESSMENT", "OTHER"])
        title = st.text_input("Title")
        claim = st.text_area("What you did (one factual sentence, include real numbers only)", max_chars=500)
        skills = st.text_input("Skills (comma-separated)")
        src = st.text_input("Proof link or document id (needed to mark VERIFIED)")
        if st.form_submit_button("Add evidence"):
            c, d = api("POST", "/evidence", {"kind": kind, "title": title, "claim_text": claim, "skills": csv(skills),
                                               "source_ref": src or None, "attributes": {}})
            ok(c, d, "Added as UNVERIFIED. Approve it below.")
    c, items = api("GET", "/evidence")
    if c != 200:
        return err(c, items)
    for e in items:
        with st.expander(f"[{e['verification_status']}] {e['title']}"):
            st.write(e["claim_text"])
            st.caption(f"Skills: {', '.join(e['skills']) or '-'} | Source: {e['source_ref'] or '-'}")
            b = st.columns(3)
            if e["verification_status"] == "UNVERIFIED" and b[0].button("Approve (I confirm this is true)", key=f"ap{e['id']}"):
                ok(*api("POST", f"/evidence/{e['id']}/approve"), rerun=True)
            if e["verification_status"] != "VERIFIED" and b[1].button("Mark VERIFIED (needs source)", key=f"vf{e['id']}"):
                ok(*api("POST", f"/evidence/{e['id']}/verify"), rerun=True)
            if b[2].button("Delete", key=f"de{e['id']}"):
                ok(*api("DELETE", f"/evidence/{e['id']}"), rerun=True)


# ---------------------------------------------------------------- jobs
def show_requirements(reqs):
    rows = [{"Level": r["level"], "Requirement": r["text"], "Skills": ", ".join(r["skills"]),
             "Checks": ", ".join(g["kind"] for g in r["gates"])} for r in reqs]
    if rows:
        st.dataframe(rows, width="stretch")
    else:
        st.info("No explicit requirements were detected.")


STATUS_ICON = {"PROVEN_BY_APPROVED_EVIDENCE": "✅ proven", "IN_CV_NOT_YET_EVIDENCED": "🟡 in CV, add evidence", "MISSING": "❌ missing"}


def show_match(m):
    if not m["skills"]:
        return st.info("No recognised skills in this posting.")
    cols = st.columns(3)
    cols[0].metric("Required skills proven", "-" if m["proven_required_pct"] is None else f"{m['proven_required_pct']}%")
    cols[1].metric("Required skills in CV or proven", "-" if m["cv_or_proven_required_pct"] is None else f"{m['cv_or_proven_required_pct']}%")
    cols[2].metric("All skills in CV or proven", "-" if m["all_skills_cv_or_proven_pct"] is None else f"{m['all_skills_cv_or_proven_pct']}%")
    st.dataframe([{"Skill": x["skill"], "Level": x["level"], "You": STATUS_ICON[x["status"]], "From the posting": x["source_quote"]}
                  for x in m["skills"]], width="stretch")
    if m["missing_required"]:
        st.write("**Required skills to build next:** " + ", ".join(m["missing_required"]))
    st.caption(m["note"])


def show_scan(d, company):
    if d["mode"] == "NOTHING_FOUND":
        return st.warning(d["note"])
    st.success(f"{'Single posting' if d['mode'] == 'SINGLE_POSTING' else 'Careers page'}: {len(d['items'])} job(s) analysed"
               + (f", {d['skipped_links']} link(s) skipped" if d["skipped_links"] else "") + ". Best matches first.")
    icon = {"HARD_MISMATCH": "🔴", "CONFIRMATION_REQUIRED": "🟡", "ELIGIBLE_ON_STATED_FACTS": "🟢"}
    for n, it in enumerate(d["items"]):
        pct = it["match"]["cv_or_proven_required_pct"]
        with st.expander(f"{icon[it['eligibility_overall']]} {it['title']} · required skills matched "
                         f"{'-' if pct is None else str(pct) + '%'} · readiness {it['readiness_score']:.0f}", expanded=n == 0):
            st.markdown(f"[Open posting]({it['url']})")
            if it["source_status"] == "FETCHED_FROM_UNVERIFIED_SITE":
                st.caption("Site is not on your trusted list, so confidence is lower. Check it is the company's official page.")
            for g in it["eligibility_gates"]:
                (st.error if g["status"] == "NOT_MET" else st.info if g["status"] != "MET" else st.success)(f"{g['kind']}: {g['message']}")
            show_match(it["match"])
            if st.button("Save this job (for full analysis, gap plan, resume, practice)", key=f"scansave{n}"):
                c, j = api("POST", "/jobs/fetch", {"url": it["url"], "company": company, "title": it["title"][:120]})
                if ok(c, j, "Saved. Open Analysis, Gap plan or Resume."):
                    S["job_id"] = j["id"]
    st.caption(d["disclaimer"])


def after_job_created(d):
    S["job_id"] = d["id"]
    st.success(f"Saved. Status: {d['verification_status']}")
    if d["quarantined"]:
        st.warning("Instruction-like text was found in this posting. It is treated purely as data and kept away from AI prompts.")
    show_requirements(d["requirements"])


def jobs_page():
    st.header("3. Jobs")
    t1, t2, t3 = st.tabs(["Paste a posting", "Analyse any URL", "My saved jobs"])
    with t1:
        st.caption("Paste the text of a posting from the company's official page.")
        with st.form("job"):
            title = st.text_input("Job title")
            comp = st.text_input("Company")
            url = st.text_input("Official URL (optional; must be on the allowlist)")
            chk = st.date_input("Date you last checked the posting", value=date.today())
            desc = st.text_area("Posting text", height=260)
            if st.form_submit_button("Analyse posting"):
                c, d = api("POST", "/jobs", {"title": title, "company": comp, "description_text": desc,
                                               "official_url": url or None, "last_checked": chk.isoformat()})
                if ok(c, d):
                    after_job_created(d)
    with t2:
        st.caption("Paste any public https careers link: a single job, or a careers/search page (RoleFit follows up to 10 job "
                   "links on the same site). Results are compared with your approved evidence and uploaded CV. "
                   "Requires the 'Job discovery' consent.")
        with st.form("scan"):
            url = st.text_input("Careers or job URL (https)")
            comp = st.text_input("Company", key="fetch_company")
            if st.form_submit_button("Analyse"):
                S["scan_result"] = api("POST", "/jobs/scan", {"url": url, "company": comp, "max_jobs": 10})
                S["scan_company"] = comp
        if "scan_result" in S:
            c, d = S["scan_result"]
            if c != 200:
                err(c, d)
            else:
                show_scan(d, S.get("scan_company") or "Unknown")
    with t3:
        c, jobs = api("GET", "/jobs")
        if c != 200:
            return err(c, jobs)
        if not jobs:
            st.info("No jobs saved yet.")
        for j in jobs:
            with st.expander(f"{j['title']} - {j['company']} ({j['verification_status']})"):
                st.caption(f"Last checked: {j['last_checked'] or 'unknown'} | URL: {j['official_url'] or '-'} | {j['requirements']} requirements")
                c, full = api("GET", f"/jobs/{j['id']}")
                if c == 200:
                    show_requirements(full["requirements"])
                if st.button("Delete this job (and its resume drafts)", key=f"dj{j['id']}"):
                    ok(*api("DELETE", f"/jobs/{j['id']}"), rerun=True)


# ---------------------------------------------------------------- analysis
def analysis_page():
    st.header("4. Eligibility, readiness & explanation")
    jid = job_picker("analysis")
    if not jid:
        return
    c, docs = api("GET", "/documents")
    doc_id = None
    if c == 200 and docs:
        doc_id = st.selectbox("Resume to run parsing diagnostics on (optional)", [None] + [d["id"] for d in docs],
                              format_func=lambda i: "None" if i is None else next(d["filename"] for d in docs if d["id"] == i))
    b = st.columns(3)
    if b[0].button("Check eligibility"):
        S[f"el{jid}"] = api("GET", f"/jobs/{jid}/eligibility")
    if b[1].button("Compute readiness score"):
        S[f"sc{jid}"] = api("POST", f"/jobs/{jid}/score", {"resume_document_id": doc_id})
    if b[2].button("Explain in plain language (AI)"):
        S[f"ex{jid}"] = api("POST", f"/jobs/{jid}/explain")
    if f"el{jid}" in S:
        c, d = S[f"el{jid}"]
        if c != 200:
            err(c, d)
        else:
            icon = {"HARD_MISMATCH": "🔴", "CONFIRMATION_REQUIRED": "🟡", "ELIGIBLE_ON_STATED_FACTS": "🟢"}[d["overall"]]
            st.subheader(f"{icon} {d['overall'].replace('_', ' ').title()}")
            st.dataframe([{"Check": g["kind"], "Status": g["status"], "Detail": g["message"]} for g in d["gates"]], width="stretch")
    if f"sc{jid}" in S:
        c, d = S[f"sc{jid}"]
        if c != 200:
            err(c, d)
        else:
            sc = d["score"]
            m = st.columns(3)
            m[0].metric("Readiness (heuristic)", f"{sc['score']:.0f} / 100")
            m[1].metric("Likely range", f"{sc['uncertainty_band'][0]:.0f} - {sc['uncertainty_band'][1]:.0f}")
            m[2].metric("Confidence", f"{sc['confidence']:.0%}")
            st.write(f"**Label:** {sc['label'].replace('_', ' ').title()}")
            if sc["hard_cap_applied"]:
                st.warning("A hard eligibility mismatch capped this score at 35. Consider an alternative route for this vacancy.")
            st.bar_chart({x["dimension"]: x["contribution"] for x in sc["dimensions"]})
            for x in sc["confirmations_needed"]:
                st.info(x)
            for x in sc["conflicts"]:
                st.warning(x["message"])
            if sc["uncovered_mandatory"]:
                st.write("**Mandatory skills without approved evidence:** " + ", ".join(sorted({s for u in sc["uncovered_mandatory"] for s in u["skills"]})))
            if sc["unknowns"]:
                st.caption("Unknown inputs: " + ", ".join(sc["unknowns"]))
            if d.get("match"):
                st.subheader("Skills: posting vs your evidence and CV")
                show_match(d["match"])
            if d.get("ats_simulation"):
                a = d["ats_simulation"]
                st.caption(a["label"])
                st.write(f"Parsing quality: {a['parse_quality']:.0%}", a["issues"] or "No issues found.")
            st.caption(sc["disclaimer"])
    if f"ex{jid}" in S:
        c, d = S[f"ex{jid}"]
        if c != 200:
            err(c, d)
        else:
            st.subheader("Plain-language summary")
            st.write(d["explanation"]["summary"])
            for s in d["explanation"]["next_steps"]:
                st.write(f"- {s}")
            st.caption(f"{d['generated_by']} | {d['disclaimer']}")


# ---------------------------------------------------------------- gap plan
def gaps_page():
    st.header("5. Gap & learning plan")
    st.caption("What you can fix, what needs confirmation and what cannot be fixed for this vacancy.")
    jid = job_picker("gaps")
    if not jid:
        return
    use_dl = st.checkbox("I know the application deadline")
    dl = st.date_input("Deadline", value=date.today()) if use_dl else None
    if st.button("Build my plan"):
        S[f"gp{jid}"] = api("POST", f"/jobs/{jid}/gaps", {"deadline": dl.isoformat() if dl else None})
    if f"gp{jid}" not in S:
        return
    c, d = S[f"gp{jid}"]
    if c != 200:
        return err(c, d)
    if d["days_left"] is not None:
        st.write(f"**Days until deadline:** {d['days_left']}")
    names = {"NOT_FIXABLE_FOR_THIS_VACANCY": "🔴 Not fixable for this vacancy", "CONFIRMATION_REQUIRED": "🟡 Needs your confirmation",
             "OMITTED_EVIDENCE": "📝 Evidence you have not approved yet", "SHORT_TERM_FIXABLE": "🟢 Short-term fixable",
             "LONG_TERM": "🔵 Long-term"}
    if not d["items"]:
        st.success("No gaps found against the requirements I could extract.")
    for cat, label in names.items():
        items = [i for i in d["items"] if i["category"] == cat]
        if not items:
            continue
        st.subheader(f"{label} ({len(items)})")
        for i in items:
            extra = []
            if i.get("estimate_days") is not None:
                extra.append(f"~{i['estimate_days']} days")
            if i.get("feasibility") and i["feasibility"] != "NO_DEADLINE_SET":
                extra.append(i["feasibility"].replace("_", " ").lower())
            st.markdown(f"**{i['topic']}** - {i['message']}  \n➡️ {i['action']}" + (f"  \n_{' | '.join(extra)}_" if extra else ""))
            if i.get("learn_link"):
                st.markdown(f"[Official documentation]({i['learn_link']})")
    st.caption(d["proof_gate"] + " " + d["note"])


# ---------------------------------------------------------------- resume
def resume_page():
    st.header("6. Resume draft")
    st.caption("Each bullet is drawn from your approved evidence. Nothing can be exported until you approve every bullet.")
    jid = job_picker("resume")
    if not jid:
        return
    ack = st.checkbox("I understand there is a hard eligibility mismatch and still want a draft")
    if st.button("Create a new draft from approved evidence"):
        c, d = api("POST", f"/jobs/{jid}/resumes", {"acknowledge_mismatch": ack})
        ok(c, d, "Draft created.")
    c, drafts = api("GET", "/resumes", params={"job_id": jid})
    if c != 200 or not drafts:
        return st.info("No drafts for this job yet.")
    rid = st.selectbox("Draft", [r["id"] for r in drafts], index=len(drafts) - 1,
                       format_func=lambda i: next(f"Draft {n + 1}: {r['approved']}/{r['bullets']} bullets approved"
                                                  for n, r in enumerate(drafts) if r["id"] == i))
    c, pv = api("GET", f"/resumes/{rid}/preview")
    if c != 200:
        return err(c, pv)
    st.markdown(pv["markdown"])
    st.divider()
    st.write("**Review bullets**")
    c, rec = api("GET", f"/resumes/{rid}")
    for b in rec["bullets"] if c == 200 else []:
        col = st.columns([6, 1])
        col[0].write(("✅ " if b["approved"] else "⬜ ") + b["text"])
        if not b["approved"] and col[1].button("Approve", key=f"ba{b['id']}"):
            ok(*api("POST", f"/resumes/{rid}/bullets/{b['id']}/approve"), rerun=True)
        with st.expander("Edit wording", expanded=False):
            new = st.text_area("Bullet text (numbers and skills must already be in the cited evidence)", b["text"], key=f"bt{b['id']}")
            if st.button("Save edit", key=f"be{b['id']}"):
                ok(*api("POST", f"/resumes/{rid}/bullets/{b['id']}/edit", {"text": new, "evidence_ids": b["evidence_ids"]}), rerun=True)
    if st.button("Export final resume"):
        c, d = api("GET", f"/resumes/{rid}/export")
        if ok(c, d):
            st.download_button("Download (Markdown)", d["markdown"], file_name="resume.md")
            st.code(d["markdown"])


# ---------------------------------------------------------------- practice
def practice_page():
    st.header("7. Assessment & interview practice")
    st.caption("Original practice questions aligned to the posting. Never use this during a live test or interview.")
    jid = job_picker("practice")
    if not jid:
        return
    col = st.columns(3)
    mode = col[0].selectbox("Mode", ["mixed", "technical", "project", "behavioural", "japan"])
    count = col[1].slider("Questions", 1, 20, 8)
    live = col[2].checkbox("A live assessment/interview is in progress right now")
    if st.button("Generate practice"):
        S[f"pr{jid}"] = api("POST", f"/jobs/{jid}/practice", {"mode": mode, "count": count, "live_assessment_active": live})
    if f"pr{jid}" in S:
        c, d = S[f"pr{jid}"]
        if c != 200:
            return err(c, d)
        if not d["questions"]:
            st.info("No questions for this mode and posting. Try 'mixed'.")
        for n, q in enumerate(d["questions"], 1):
            st.markdown(f"**{n}. [{q['type'].replace('_', ' ').title()}]** {q['question']}")
            st.caption(q["why"])
        st.caption(d["integrity"] + " " + d["note"])


# ---------------------------------------------------------------- applications
def applications_page():
    st.header("8. Application tracker")
    c, jobs = api("GET", "/jobs")
    if c == 200 and jobs:
        with st.form("app", clear_on_submit=True):
            jid = st.selectbox("Job", [j["id"] for j in jobs], format_func=lambda i: next(f"{j['title']} - {j['company']}" for j in jobs if j["id"] == i))
            col = st.columns(2)
            stage = col[0].selectbox("Stage", STAGES)
            use_dl = col[1].checkbox("Set a deadline")
            dl = col[1].date_input("Deadline", value=date.today())
            nxt = st.text_input("Next action")
            if st.form_submit_button("Track application"):
                ok(*api("POST", "/applications", {"job_id": jid, "stage": stage, "deadline": dl.isoformat() if use_dl else None,
                                                  "next_action": nxt or None}), rerun=True)
    else:
        st.info("Add a job first.")
    c, apps = api("GET", "/applications")
    for a in apps if c == 200 else []:
        with st.expander(f"{a['title']} - {a['company']}: {a['stage']}"):
            st.caption(f"Deadline: {a.get('deadline') or '-'} | Next: {a.get('next_action') or '-'}")
            st.write(" → ".join(h["stage"] for h in a["history"]))
            col = st.columns([3, 1, 1])
            ns = col[0].selectbox("Move to", STAGES, index=STAGES.index(a["stage"]), key=f"st{a['id']}")
            if col[1].button("Update", key=f"up{a['id']}"):
                ok(*api("PATCH", f"/applications/{a['id']}", {"stage": ns}), rerun=True)
            if col[2].button("Delete", key=f"da{a['id']}"):
                ok(*api("DELETE", f"/applications/{a['id']}"), rerun=True)
    c, o = api("GET", "/applications/outcomes")
    if c == 200 and o["total"]:
        st.subheader("Outcomes")
        st.bar_chart(o["ever_reached"])
        st.caption(o["calibration"])


# ---------------------------------------------------------------- explore
def explore_page():
    st.header("9. Industries & companies")
    c, d = api("GET", "/industries/fit")
    if c == 200:
        st.subheader("Industry fit")
        st.dataframe([{"Industry": r["industry"], "Score": r["score"], "Preferred": "✓" if r["preference_match"] else "",
                       "Matched skills": ", ".join(r["matched_skills"]), "Missing core skills": ", ".join(r["missing_core_skills"])}
                      for r in d["ranking"]], width="stretch")
        st.caption(d["method"] + " " + d["note"])
    else:
        err(c, d)
    st.subheader("My company watchlist")
    with st.form("co", clear_on_submit=True):
        col = st.columns(2)
        name = col[0].text_input("Company")
        ind = col[1].text_input("Industry")
        country = col[0].text_input("Country")
        url = col[1].text_input("Official careers URL (https) - Greenhouse, Lever or Ashby URLs enable automatic alerts")
        if st.form_submit_button("Add company"):
            ok(*api("POST", "/companies", {"name": name, "industry": ind or None, "country": country or None,
                                           "careers_url": url or None}), rerun=True)
    c, cos = api("GET", "/companies")
    for co in cos if c == 200 else []:
        col = st.columns([5, 1])
        link = f" - [careers]({co['careers_url']})" if co.get("careers_url") else ""
        col[0].markdown(f"**{co['name']}** ({co.get('industry') or '-'}, {co.get('country') or '-'}){link}"
                        + (f" - 🔔 automatic alerts ({co['ats']})" if co.get("auto_alerts") else "")
                        + (" - fetchable" if co["fetch_allowed"] else ""))
        if co.get("alerts_note"):
            col[0].caption(co["alerts_note"])
        if col[1].button("Remove", key=f"rc{co['id']}"):
            ok(*api("DELETE", f"/companies/{co['id']}"), rerun=True)


# ---------------------------------------------------------------- alerts
def alerts_page():
    st.header("🔔 Job alerts")
    c, ds = api("GET", "/discovery/status")
    if c != 200:
        return err(c, ds)
    if not ds["consent"]:
        st.warning("Turn on the **Job discovery** consent on the Profile page to receive alerts.")
    if not ds["companies_with_auto_alerts"] and not ds["feeds"]:
        st.info("Follow companies on the **Industries & companies** page using their official Greenhouse, Lever or Ashby "
                "careers URL. RoleFit then checks them automatically.")
    if ds["email_alerts_on"] and not ds["email_configured"]:
        st.warning("Email alerts are on, but the server has no email settings yet (ROLEFIT_SMTP_* in .env, see README).")
    elif ds["email_alerts_on"]:
        st.caption("📧 New alerts are also emailed to you.")
    every = ds["scheduler_interval_hours"]
    st.caption((f"Checked automatically every {every:g} hours. " if every else "Automatic checks are off on this server. ")
               + ds["sources"])
    if st.button("Check now"):
        c, r = api("POST", "/alerts/refresh")
        if ok(c, r, f"Checked {r.get('checked_companies', 0)} companies: {r.get('new_alerts', 0)} new alerts."):
            for e in r["errors"]:
                st.warning(f"{e['company']}: {e['error']}")
    with st.expander("Google Alerts feeds (openings from any website)"):
        st.markdown("1. Go to [google.com/alerts](https://www.google.com/alerts) and create an alert, e.g. "
                    "`\"machine learning intern\" India 2027`.\n2. Click **Show options → Deliver to: RSS feed**, then "
                    "**Create alert**.\n3. Copy the RSS icon's link and paste it here.")
        with st.form("feed", clear_on_submit=True):
            furl = st.text_input("Google Alerts RSS feed URL")
            flabel = st.text_input("Label (optional)")
            if st.form_submit_button("Add feed"):
                ok(*api("POST", "/feeds", {"url": furl, "label": flabel or None}), rerun=True)
        c, feeds = api("GET", "/feeds")
        for f in feeds if c == 200 else []:
            col = st.columns([5, 1])
            col[0].write(f"📡 {f.get('label') or f['url']}")
            if col[1].button("Remove", key=f"rf{f['id']}"):
                ok(*api("DELETE", f"/feeds/{f['id']}"), rerun=True)
    show = st.radio("Show", ["NEW", "SAVED", "DISMISSED", "NO_LONGER_LISTED", "All"], horizontal=True)
    c, alerts = api("GET", "/alerts", params=None if show == "All" else {"status": show})
    if c != 200:
        return err(c, alerts)
    if not alerts:
        st.write("No alerts here yet.")
    icon = {"HARD_MISMATCH": "🔴", "CONFIRMATION_REQUIRED": "🟡", "ELIGIBLE_ON_STATED_FACTS": "🟢"}
    for a in alerts:
        score = "lead from Google Alerts" if a.get("lead_only") else f"readiness {a['readiness_score']:.0f}"
        with st.expander(f"{icon.get(a['eligibility_overall'], '🔗')} {a['title']} - {a['company']} ({a['location'] or '-'}) · {score}"):
            st.markdown(f"[Open the official posting]({a['url']})" if a["url"] else "No link provided")
            st.caption(" · ".join(a["match_reasons"]) + (f" · published {a['published']}" if a["published"] else ""))
            if a.get("lead_only"):
                st.info("Only a snippet is available. Open the link and, if it fits, paste or fetch the full posting on the Jobs page.")
            else:
                st.write(f"Eligibility: **{a['eligibility_overall'].replace('_', ' ').title()}**")
            if a["uncovered_mandatory"]:
                st.write("Mandatory skills without approved evidence: " + ", ".join(a["uncovered_mandatory"]))
            if a["quarantined"]:
                st.warning("This posting contains instruction-like text; it is treated purely as data.")
            if a["status"] in ("NEW", "SEEN", "NO_LONGER_LISTED"):
                b = st.columns(2)
                if not a.get("lead_only") and b[0].button("Save as a job (full analysis, resume, practice)", key=f"sv{a['id']}"):
                    c2_, j = api("POST", f"/alerts/{a['id']}/save")
                    if ok(c2_, j):
                        S["job_id"] = j["id"]
                        st.success("Saved. Open Analysis, Gap plan or Resume to continue.")
                if b[1].button("Dismiss", key=f"ds{a['id']}"):
                    ok(*api("POST", f"/alerts/{a['id']}/dismiss"), rerun=True)


# ---------------------------------------------------------------- privacy
def privacy_page():
    st.header("10. Privacy, export & deletion")
    c, d = api("GET", "/me/export")
    if c == 200:
        st.download_button("Download all my data (JSON)", json.dumps(d, indent=2), file_name="rolefit-export.json")
    c, a = api("GET", "/audit")
    if c == 200:
        st.subheader("Activity log")
        st.dataframe(a[-50:], width="stretch")
    st.subheader("Delete my account and data")
    pw = st.text_input("Re-enter your password to confirm", type="password", key="del_pw")
    if st.button("Delete everything permanently"):
        c, d = api("DELETE", "/me", {"password": pw})
        if c == 200:
            S.clear()
            st.success("Deleted. Receipt: " + d["receipt"])
        else:
            err(c, d)


PAGES = {"Job alerts": alerts_page, "Profile": profile_page, "Evidence": evidence_page, "Jobs": jobs_page, "Analysis": analysis_page,
         "Gap plan": gaps_page, "Resume": resume_page, "Practice": practice_page, "Applications": applications_page,
         "Industries & companies": explore_page, "Privacy": privacy_page}

st.title("🧭 RoleFit AI Career Navigator")
st.caption("Not an employer ATS score and not a guarantee of selection.")
if not S.get("token"):
    auth_page()
else:
    with st.sidebar:
        nav = st.radio("Steps", list(PAGES), key="nav")
        if st.button("Sign out"):
            api("POST", "/auth/logout")
            S.clear()
            st.rerun()
    PAGES[nav]()
