"""Automatic job alerts. For every candidate who consented to job discovery, check the official job boards of the
companies they follow, keep postings that match their profile, and store them as alerts with an eligibility check
and readiness score. Runs on a schedule (background thread) and on demand."""
import logging
import re
import threading
import time
from datetime import date

from ..core import eligibility, requirements as reqcore, scoring
from ..schemas import Profile
from ..security import injection
from ..security.fetcher import FetchError
from .connectors import fetch_board
from .feeds import fetch_alerts_feed

log = logging.getLogger("rolefit.discovery")

DEFAULT_ROLES = ["machine learning", "ml", "ai", "data", "software", "engineer", "developer", "analyst", "research"]
EARLY = re.compile(r"\b(intern(ship)?s?|graduates?|new grad|grad(uate)? program|entry[- ]level|junior|fresher|campus|"
                   r"trainee|apprentice|early career|20(2[6-9]|30) (start|graduates?|joiners?))\b|新卒|インターン", re.I)
SENIOR = re.compile(r"\b(senior|sr\.?|staff|principal|lead|manager|director|head of|vp|architect)\b", re.I)
PLACES = {
    "japan": ["japan", "tokyo", "osaka", "kyoto", "fukuoka", "yokohama", "nagoya", "日本", "東京"],
    "india": ["india", "bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi", "gurgaon", "gurugram", "noida",
              "chennai", "kolkata", "indore", "ahmedabad"],
    "singapore": ["singapore"],
    "germany": ["germany", "berlin", "munich", "hamburg", "frankfurt"],
    "united kingdom": ["united kingdom", "uk", "london", "england"],
    "united states": ["united states", "usa", "us", "new york", "san francisco", "seattle", "boston", "austin"],
    "taiwan": ["taiwan", "taipei"],
}


def _places(countries: list) -> list:
    out = []
    for c in countries:
        c = c.strip().lower()
        out += PLACES.get(c, [c])
    return out


def match(posting, profile: Profile) -> tuple:
    """Return (is_match, reasons). Deterministic, explainable filters only."""
    title, loc, text = posting.title.lower(), posting.location.lower(), posting.description_text.lower()
    roles = [r.lower() for r in profile.target_roles] or DEFAULT_ROLES
    hit_roles = [r for r in roles if re.search(r"(?<!\w)" + re.escape(r) + r"(?!\w)", title)]
    if not hit_roles:
        return False, ["Title does not match your target roles"]
    reasons = [f"Title matches: {', '.join(hit_roles[:3])}"]
    if profile.early_career_only:
        if SENIOR.search(posting.title):
            return False, ["Senior-level title"]
        early = EARLY.search(posting.title) or EARLY.search(text[:4000])
        if not early:
            return False, ["No internship/graduate/entry-level signal"]
        reasons.append(f"Early-career signal: '{early.group(0)}'")
    if profile.countries:
        places = _places(profile.countries)
        rx = lambda p_: re.compile(r"(?<!\w)" + re.escape(p_) + r"(?!\w)")
        hit = next((p_ for p_ in places if rx(p_).search(loc)), None)
        if not hit:  # fall back to the description, but only for unambiguous names (not "us", "uk")
            hit = next((p_ for p_ in places if len(p_) >= 5 and rx(p_).search(text[:1500])), None)
        if not hit and "remote" not in loc:
            return False, ["Location is not in your preferred countries"]
        reasons.append(f"Location: {posting.location or 'remote'}")
    return True, reasons


def match_lead(posting, profile: Profile) -> tuple:
    """Looser match for short Google Alerts snippets: role + (if required) early-career signal; location noted if seen."""
    text = posting.title + " " + posting.description_text
    roles = [r.lower() for r in profile.target_roles] or DEFAULT_ROLES
    hit = [r for r in roles if re.search(r"(?<!\w)" + re.escape(r) + r"(?!\w)", text.lower())]
    if not hit:
        return False, ["No target role in the snippet"]
    reasons = [f"Mentions: {', '.join(hit[:3])}"]
    if profile.early_career_only:
        if SENIOR.search(posting.title):
            return False, ["Senior-level title"]
        early = EARLY.search(text)
        if not early:
            return False, ["No internship/graduate/entry-level signal"]
        reasons.append(f"Early-career signal: '{early.group(0)}'")
    place = next((p for p in _places(profile.countries) if len(p) >= 5 and p in text.lower()), None)
    reasons.append(f"Location mentioned: {place}" if place else "Location not stated in the snippet")
    return True, reasons


def run_for_user(db, user_id: str, resolve=True, resolver=None, transport=None, cache=None, today=None,
                 notifier=None, feed_transport=None) -> dict:
    today = today or date.today()
    cache = {} if cache is None else cache
    rows = db.list_owned("profile", user_id)
    profile = Profile(**{k: v for k, v in rows[0].items() if k != "id"}) if rows else Profile()
    if not profile.consents.job_discovery:
        return {"status": "SKIPPED_NO_CONSENT", "new_alerts": 0, "checked_companies": 0, "errors": []}
    companies = [c for c in db.list_owned("company", user_id) if c.get("ats") and c.get("board")]
    evidence = db.list_owned("evidence", user_id)
    existing = {a["key"]: a for a in db.list_owned("alert", user_id)}
    new, errors, seen_keys, checked, fresh = 0, [], set(), 0, []
    for c in companies:
        ck = (c["ats"], c["board"])
        if ck not in cache:
            try:
                cache[ck] = fetch_board(c["ats"], c["board"], c["name"], resolve, resolver, transport)
            except (FetchError, ValueError) as e:
                cache[ck] = e
        result = cache[ck]
        if isinstance(result, Exception):
            errors.append({"company": c["name"], "error": str(result)})
            continue
        checked += 1
        for p in result:
            seen_keys.add(p.key)
            if p.key in existing:
                continue
            ok, reasons = match(p, profile)
            if not ok:
                continue
            reqs = reqcore.extract_requirements(p.description_text)
            elig = eligibility.evaluate(reqs, profile)
            sc = scoring.compute(reqs, evidence, profile, elig, None, today.isoformat(), today,
                                 "FETCHED_FROM_ALLOWLISTED_OFFICIAL_SOURCE")
            findings = injection.scan(p.description_text)
            db.put("alert", user_id, {
                "key": p.key, "source": p.source, "company": p.company or c["name"], "title": p.title, "location": p.location,
                "url": p.url, "published": p.published, "description_text": p.description_text, "match_reasons": reasons,
                "eligibility_overall": elig["overall"], "readiness_score": sc["score"], "confidence": sc["confidence"],
                "uncovered_mandatory": sorted({s for u in sc["uncovered_mandatory"] for s in u["skills"]}),
                "findings": findings, "quarantined": bool(findings), "status": "NEW", "found_at": time.time()})
            new += 1
            fresh.append({"title": p.title, "company": p.company or c["name"], "location": p.location, "url": p.url,
                          "readiness_score": sc["score"]})
    # Google Alerts feeds -> leads (snippets only; the candidate opens the link to analyse the full posting)
    feeds = db.list_owned("feed", user_id)
    for f in feeds:
        fk = ("feed", f["url"])
        if fk not in cache:
            try:
                cache[fk] = fetch_alerts_feed(f["url"], resolve, resolver, feed_transport or transport)
            except (FetchError, ValueError) as e:
                cache[fk] = e
        result = cache[fk]
        if isinstance(result, Exception):
            errors.append({"company": f.get("label") or "Google Alerts feed", "error": str(result)})
            continue
        checked += 1
        for p in result:
            if p.key in existing or p.key in seen_keys or not p.url:
                continue
            ok, reasons = match_lead(p, profile)
            if not ok:
                continue
            findings = injection.scan(p.title + " " + p.description_text)
            db.put("alert", user_id, {
                "key": p.key, "source": p.source, "company": p.company, "title": p.title, "location": "", "url": p.url,
                "published": p.published, "description_text": p.description_text, "match_reasons": reasons,
                "eligibility_overall": "UNKNOWN_OPEN_FULL_POSTING", "readiness_score": None, "confidence": None,
                "uncovered_mandatory": [], "findings": findings, "quarantined": bool(findings), "status": "NEW",
                "found_at": time.time(), "lead_only": True})
            seen_keys.add(p.key)
            new += 1
            fresh.append({"title": p.title, "company": p.company, "location": "", "url": p.url, "readiness_score": None})
    emailed = False
    if fresh and notifier is not None and notifier.enabled and profile.email_alerts:
        user = db.user_by_id(user_id)
        if user:
            try:
                notifier.send(user["email"], fresh)
                emailed = True
            except Exception as e:  # never fail the run because email failed
                errors.append({"company": "email", "error": f"Could not send the alert email ({type(e).__name__})"})
    # Postings that disappeared from a board we checked successfully are marked, never silently deleted.
    ok_boards = {f"{c['ats']}:{c['board']}:" for c in companies if not isinstance(cache.get((c["ats"], c["board"])), Exception)}
    for a in existing.values():
        if a["status"] in ("NEW", "SEEN") and any(a["key"].startswith(b) for b in ok_boards) and a["key"] not in seen_keys:
            a["status"] = "NO_LONGER_LISTED"
            db.update_owned("alert", a["id"], user_id, {k: v for k, v in a.items() if k != "id"})
    db.audit(user_id, "discovery.run", meta={"new": new, "sources": checked, "errors": len(errors), "emailed": emailed})
    return {"status": "OK", "new_alerts": new, "checked_companies": checked, "errors": errors, "emailed": emailed}


class Scheduler:
    """Background loop: every `interval` seconds, refresh alerts for every user who follows companies."""

    def __init__(self, db, interval_seconds: float, resolve=True, resolver=None, transport=None, notifier=None):
        self.db, self.interval, self.notifier = db, interval_seconds, notifier
        self.resolve, self.resolver, self.transport = resolve, resolver, transport
        self._stop = threading.Event()
        self._thread = None
        self.last_run, self.next_run = None, None

    def run_once(self):
        cache = {}  # each company board is fetched once per cycle, however many users follow it
        for uid in sorted(set(self.db.owners_of("company")) | set(self.db.owners_of("feed"))):
            try:
                run_for_user(self.db, uid, self.resolve, self.resolver, self.transport, cache, notifier=self.notifier)
            except Exception:  # one user's failure must not stop the others
                log.exception("discovery failed for a user")
        self.last_run = time.time()

    def _loop(self):
        self._stop.wait(5)  # let the API finish starting
        while not self._stop.is_set():
            self.run_once()
            self.next_run = time.time() + self.interval
            self._stop.wait(self.interval)

    def start(self):
        if self.interval > 0 and not self._thread:
            self._thread = threading.Thread(target=self._loop, name="rolefit-discovery", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
