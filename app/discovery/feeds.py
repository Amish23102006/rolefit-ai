"""Google Alerts (RSS delivery) as a lead source. The candidate creates an alert on google.com/alerts with
"Deliver to: RSS feed" and pastes the feed URL. This is Google's own feature, so nothing is scraped.
Feed entries are short snippets, so they become LEADS: matched on title/snippet only, never fully scored."""
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

from ..security.fetcher import fetch_feed, html_to_text
from .connectors import Posting

FEED_HOSTS = ("www.google.com",)
ATOM = "{http://www.w3.org/2005/Atom}"


def is_google_alerts_feed(url: str) -> bool:
    p = urlsplit(url.strip())
    return p.scheme == "https" and (p.hostname or "").lower() == "www.google.com" and p.path.startswith("/alerts/feeds/") \
        and bool(re.fullmatch(r"/alerts/feeds/\d{1,30}/\d{1,30}", p.path))


def _real_link(href: str) -> str:
    """Google Alerts wraps links as https://www.google.com/url?...&url=<target>. Return the target if it is https."""
    q = parse_qs(urlsplit(href).query)
    target = (q.get("url") or [href])[0]
    return target if target.startswith("https://") else ""


def parse_feed(body: bytes, feed_id: str) -> list:
    if b"<!DOCTYPE" in body[:2000].upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Feed contains a DTD/entities; rejected")
    root = ET.fromstring(body)
    out = []
    for e in root.findall(f"{ATOM}entry"):
        title = html_to_text(e.findtext(f"{ATOM}title") or "")[0]
        snippet = html_to_text(e.findtext(f"{ATOM}content") or "")[0]
        link_el = e.find(f"{ATOM}link")
        link = _real_link(link_el.get("href", "")) if link_el is not None else ""
        eid = e.findtext(f"{ATOM}id") or link
        if not (title and eid):
            continue
        host = (urlsplit(link).hostname or "web") if link else "web"
        out.append(Posting("google_alerts", feed_id, eid[-120:], title[:200], host, "", link, snippet[:2000],
                           (e.findtext(f"{ATOM}published") or "")[:10] or None))
    return out


def fetch_alerts_feed(url: str, resolve=True, resolver=None, transport=None) -> list:
    if not is_google_alerts_feed(url):
        raise ValueError("Only Google Alerts RSS feed URLs are supported")
    feed_id = urlsplit(url).path.rsplit("/", 1)[-1]
    try:
        return parse_feed(fetch_feed(url, FEED_HOSTS, resolve, resolver, transport), feed_id)
    except ET.ParseError:
        raise ValueError("Feed is not valid XML")
