"""Find individual job-posting links on a careers listing page (static HTML only; nothing is executed)."""
import re
from urllib.parse import urlsplit

JOB_PATH = re.compile(r"/(jobs?|careers?|positions?|openings?|vacanc\w*|requisitions?|postings?|opportunit\w*|roles?|results)(/|$)", re.I)
ID_LIKE = re.compile(r"(\d{3,})|([a-z0-9]+(-[a-z0-9]+){3,})", re.I)
EXCLUDE = re.compile(r"(login|signin|sign-in|register|apply\?|search\?|[?&]page=|privacy|cookie|benefits|locations?|teams?/?$|"
                     r"students/?$|faq|blog|news|events?|talent-?community|\.pdf$|\.jpg$|\.png$)", re.I)


def _site(host: str) -> str:
    parts = host.lower().split(".")
    return ".".join(parts[-3:]) if len(parts) > 2 and len(parts[-1]) == 2 and len(parts[-2]) <= 3 else ".".join(parts[-2:])


def job_links(links: list, page_url: str, limit: int = 10) -> list:
    base = urlsplit(page_url)
    site = _site(base.hostname or "")
    out = []
    for u in links:
        p = urlsplit(u)
        host = (p.hostname or "").lower()
        if not (host == site or host.endswith("." + site)):
            continue
        path = p.path.rstrip("/")
        if u.rstrip("/") == page_url.rstrip("/") or EXCLUDE.search(u):
            continue
        last = path.rsplit("/", 1)[-1]
        if JOB_PATH.search(path + "/") and ID_LIKE.search(last):
            out.append(u)
        if len(out) >= limit:
            break
    return out
