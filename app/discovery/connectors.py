"""Official job-board connectors (documented public APIs only; no scraping, no logins, no search engines).

Supported: Greenhouse Job Board API, Lever Postings API, Ashby Job Board API. A company is identified by the
board name in its official careers URL, e.g. https://boards.greenhouse.io/<board>, https://jobs.lever.co/<board>,
https://jobs.ashbyhq.com/<board>."""
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from ..security.fetcher import fetch_json, html_to_text

# Fixed API hosts. These are NOT user-configurable: the user only chooses which companies to follow.
API_HOSTS = ("boards-api.greenhouse.io", "api.lever.co", "api.eu.lever.co", "api.ashbyhq.com")
_BOARD = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


@dataclass
class Posting:
    source: str
    board: str
    external_id: str
    title: str
    company: str
    location: str
    url: str
    description_text: str
    published: Optional[str]  # ISO date if the board provides one

    @property
    def key(self) -> str:
        return f"{self.source}:{self.board}:{self.external_id}"


def detect_board(careers_url: str) -> Optional[tuple]:
    """Return (ats, board) from an official careers URL, or None if it is not a supported platform."""
    try:
        p = urlsplit(careers_url.strip())
    except ValueError:
        return None
    if p.scheme != "https":
        return None
    host = (p.hostname or "").lower()
    seg = [s for s in p.path.split("/") if s]
    board = None
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io"):
        board = parse_qs(p.query).get("for", [None])[0] if seg[:2] == ["embed", "job_board"] else (seg[0] if seg else None)
        ats = "greenhouse"
    elif host == "jobs.lever.co":
        board, ats = (seg[0] if seg else None), "lever"
    elif host == "jobs.eu.lever.co":
        board, ats = (seg[0] if seg else None), "lever_eu"
    elif host == "jobs.ashbyhq.com":
        board, ats = (seg[0] if seg else None), "ashby"
    else:
        return None
    return (ats, board) if board and _BOARD.match(board) else None


def _iso(value) -> Optional[str]:
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, timezone.utc).date().isoformat()
        if isinstance(value, str) and value:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, OSError, OverflowError):
        pass
    return None


def _clean_html(fragment: str) -> str:
    s = fragment or ""
    for _ in range(2):  # Greenhouse returns entity-encoded HTML (sometimes twice)
        if "&lt;" not in s and "&amp;" not in s:
            break
        s = html.unescape(s)
    return html_to_text(s)[0]


def fetch_board(ats: str, board: str, company: str, resolve=True, resolver=None, transport=None) -> list:
    if not _BOARD.match(board or ""):
        raise ValueError("Invalid board name")
    if ats == "greenhouse":
        data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true", API_HOSTS, resolve, resolver, transport)
        return [Posting("greenhouse", board, str(j.get("id")), str(j.get("title", ""))[:200], company,
                        str((j.get("location") or {}).get("name", ""))[:200], str(j.get("absolute_url", "")),
                        _clean_html(j.get("content", ""))[:20000], _iso(j.get("updated_at") or j.get("first_published")))
                for j in (data.get("jobs") or []) if j.get("id")]
    if ats in ("lever", "lever_eu"):
        host = "api.eu.lever.co" if ats == "lever_eu" else "api.lever.co"
        data = fetch_json(f"https://{host}/v0/postings/{board}?mode=json", API_HOSTS, resolve, resolver, transport)
        out = []
        for j in data if isinstance(data, list) else []:
            if not j.get("id"):
                continue
            parts = [j.get("descriptionPlain") or ""]
            for lst in j.get("lists") or []:
                parts.append(str(lst.get("text", "")) + ":\n" + _clean_html(lst.get("content", "")))
            parts.append(j.get("additionalPlain") or "")
            cat = j.get("categories") or {}
            out.append(Posting(ats, board, str(j["id"]), str(j.get("text", ""))[:200], company,
                               str(cat.get("location", ""))[:200], str(j.get("hostedUrl", "")),
                               "\n".join(p for p in parts if p)[:20000], _iso(j.get("createdAt"))))
        return out
    if ats == "ashby":
        data = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}", API_HOSTS, resolve, resolver, transport)
        out = []
        for j in data.get("jobs") or []:
            jid = j.get("id") or j.get("jobUrl")  # the public API documents jobUrl; id may be absent
            if not jid or j.get("isListed") is False:
                continue
            loc = str(j.get("location", "")) + (" (Remote)" if j.get("isRemote") else "")
            out.append(Posting("ashby", board, str(jid), str(j.get("title", ""))[:200], company, loc[:200],
                               str(j.get("jobUrl", "")), (j.get("descriptionPlain") or _clean_html(j.get("descriptionHtml", "")))[:20000],
                               _iso(j.get("publishedAt"))))
        return out
    raise ValueError(f"Unsupported platform: {ats}")
