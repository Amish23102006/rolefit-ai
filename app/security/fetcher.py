"""Safe fetcher for official job pages (Opportunity Verification agent).

Rules: the URL must pass validate_url() (https, allowlisted official domain, public DNS); every redirect hop is
re-validated (max 3); response size, time and content type are capped; HTML is reduced to plain text with the
standard-library parser (scripts/styles dropped, nothing executed). The fetched text is UNTRUSTED DATA and goes
through the same injection scan and deterministic requirement extraction as pasted text.
"""
import hashlib
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, Optional
from urllib.parse import urljoin

import httpx

from .ssrf import UnsafeURL, validate_url

MAX_REDIRECTS = 3
TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml")
CLOSED_PATTERNS = re.compile(
    r"no longer (accepting applications|available|open)|position has been filled|job (has been )?(closed|expired)|"
    r"(posting|job|position) (is )?(not found|unavailable)|this (job|role) is closed", re.I)
USER_AGENT = "RoleFitAI-Verifier/0.2 (+candidate-directed, low-volume)"


class FetchError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    http_status: int
    text: str
    title: str
    sha256: str
    fetched_at: float
    status: str  # OPEN_ON_OFFICIAL_SOURCE | CLOSED_OR_UNAVAILABLE
    links: list = field(default_factory=list)  # absolute https links found on the page (for listing pages)


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.title, self._skip, self._in_title, self.links = [], "", 0, False, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href and len(self.links) < 2000:
                self.links.append(href)
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "li":
            self.parts.append("\n- ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def extract_links(html: str, base_url: str) -> list:
    p = _TextExtractor()
    p.feed(html)
    p.close()
    out, seen = [], set()
    for h in p.links:
        u = urljoin(base_url, h.strip()).split("#")[0]
        if u.startswith("https://") and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def html_to_text(html: str) -> tuple[str, str]:
    p = _TextExtractor()
    p.feed(html)
    p.close()
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, " ".join(p.title.split())[:200]


def fetch_official_page(url: str, allowed_domains: tuple, resolve: bool = True, resolver=None,
                        transport: Optional[httpx.BaseTransport] = None, max_bytes: int = 2 * 1024 * 1024,
                        timeout: float = 10.0, clock: Callable[[], float] = time.time) -> FetchResult:
    current = url
    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False,
                      headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain"}) as client:
        for hop in range(MAX_REDIRECTS + 1):
            try:
                current = validate_url(current, allowed_domains, resolve, resolver)
            except UnsafeURL as e:
                raise FetchError(f"URL rejected{' after redirect' if hop else ''}: {e}")
            try:
                with client.stream("GET", current) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("location")
                        if not loc:
                            raise FetchError("Redirect without a location", 502)
                        current = urljoin(current, loc)
                        continue
                    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    if r.status_code in (404, 410):
                        return FetchResult(url, current, r.status_code, "", "", "", clock(), "CLOSED_OR_UNAVAILABLE")
                    if r.status_code != 200:
                        raise FetchError(f"Official page returned HTTP {r.status_code}; unable to verify", 502)
                    if ctype not in TEXT_TYPES:
                        raise FetchError("Official page is not an HTML/text document")
                    body = b""
                    for chunk in r.iter_bytes():
                        body += chunk
                        if len(body) > max_bytes:
                            raise FetchError("Official page is too large")
                    raw = body.decode(r.encoding or "utf-8", "replace")
            except httpx.TimeoutException:
                raise FetchError("Official page timed out; unable to verify", 504)
            except httpx.TransportError:
                raise FetchError("Could not connect to the official page; unable to verify", 502)
            text, title = html_to_text(raw) if ctype != "text/plain" else (raw.strip(), "")
            status = "CLOSED_OR_UNAVAILABLE" if CLOSED_PATTERNS.search(text[:5000]) else "OPEN_ON_OFFICIAL_SOURCE"
            links = extract_links(raw, current) if ctype != "text/plain" else []
            return FetchResult(url, current, 200, text[:20000], title, hashlib.sha256(body).hexdigest(), clock(), status, links)
    raise FetchError("Too many redirects")


def fetch_json(url: str, allowed_domains: tuple, resolve: bool = True, resolver=None,
               transport: Optional[httpx.BaseTransport] = None, max_bytes: int = 8 * 1024 * 1024,
               timeout: float = 15.0):
    """GET a documented public JSON API with the same SSRF rules as page fetching (per-hop validation, caps)."""
    import json as _json
    current = url
    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False,
                      headers={"User-Agent": USER_AGENT, "Accept": "application/json"}) as client:
        for hop in range(MAX_REDIRECTS + 1):
            try:
                current = validate_url(current, allowed_domains, resolve, resolver)
            except UnsafeURL as e:
                raise FetchError(f"URL rejected{' after redirect' if hop else ''}: {e}")
            try:
                with client.stream("GET", current) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("location")
                        if not loc:
                            raise FetchError("Redirect without a location", 502)
                        current = urljoin(current, loc)
                        continue
                    if r.status_code == 404:
                        raise FetchError("Job board not found (check the company's board name)", 404)
                    if r.status_code != 200:
                        raise FetchError(f"Job board API returned HTTP {r.status_code}", 502)
                    body = b""
                    for chunk in r.iter_bytes():
                        body += chunk
                        if len(body) > max_bytes:
                            raise FetchError("Job board response is too large")
            except httpx.TimeoutException:
                raise FetchError("Job board API timed out", 504)
            except httpx.TransportError:
                raise FetchError("Could not connect to the job board API", 502)
            try:
                return _json.loads(body)
            except ValueError:
                raise FetchError("Job board API did not return valid JSON", 502)
    raise FetchError("Too many redirects")


FEED_TYPES = ("application/atom+xml", "application/rss+xml", "application/xml", "text/xml")


def fetch_feed(url: str, allowed_domains: tuple, resolve: bool = True, resolver=None,
               transport: Optional[httpx.BaseTransport] = None, max_bytes: int = 2 * 1024 * 1024, timeout: float = 15.0) -> bytes:
    """GET an RSS/Atom feed with the same SSRF rules (no redirects followed)."""
    try:
        url = validate_url(url, allowed_domains, resolve, resolver)
    except UnsafeURL as e:
        raise FetchError(f"Feed URL rejected: {e}")
    try:
        with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False,
                          headers={"User-Agent": USER_AGENT, "Accept": ", ".join(FEED_TYPES)}) as client:
            with client.stream("GET", url) as r:
                if r.status_code != 200:
                    raise FetchError(f"Feed returned HTTP {r.status_code}", 502)
                if r.headers.get("content-type", "").split(";")[0].strip().lower() not in FEED_TYPES:
                    raise FetchError("URL is not an RSS/Atom feed")
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise FetchError("Feed is too large")
                return body
    except httpx.TimeoutException:
        raise FetchError("Feed timed out", 504)
    except httpx.TransportError:
        raise FetchError("Could not connect to the feed", 502)
