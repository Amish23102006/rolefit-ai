"""Deterministic job-requirement extraction with source spans. No model; cannot be prompt-injected."""
import re

from ..schemas import HardGate, Level, Requirement, Span
from .skills import find_skills

MANDATORY_HDR = ("requirement", "must have", "must-have", "required", "qualification", "what you need",
                 "what we need", "minimum", "you have", "you bring")
PREFERRED_HDR = ("preferred", "nice to have", "nice-to-have", "bonus", "desirable", "good to have")
OTHER_HDR = ("responsibilit", "about", "benefit", "what you will do", "what you'll do", "overview",
             "who we are", "we offer", "our team", "the role", "perks")
INLINE_PREFERRED = re.compile(r"\b(preferred|nice to have|a plus|bonus|desirable|good to have)\b", re.I)
INLINE_MANDATORY = re.compile(r"\b(required|must|minimum|mandatory|need to have)\b", re.I)
BULLET = re.compile(r"^\s*([-*\u2022\u25cf]|\d+[.)])\s+")

LANG_CEFR = re.compile(r"\b(english|german|french|spanish|japanese)\b[^\n.]{0,40}?\b([ABC][12])\b", re.I)
GRAD_A = re.compile(r"graduat\w*([^.\n]{0,60})", re.I)
GRAD_B = re.compile(r"(?:class|batch) of (20\d{2})|(20\d{2}) (?:graduates|graduating|graduation)", re.I)
NO_SPONSOR = re.compile(r"(\b(no|not|cannot|unable to|without)\b[^.\n]{0,30}visa sponsorship)|"
                        r"(visa sponsorship[^.\n]{0,20}(not|unavailable|isn't|is not)\b)|"
                        r"(sponsorship[^.\n]{0,25}not (available|provided|offered))", re.I)
WORK_AUTH = re.compile(r"(?:authori[sz]ed|eligible|right|permission|permitted) to work in (?:the )?"
                       r"([A-Za-z][A-Za-z ]{1,25}?)(?=[.,;]|\bwithout\b|\bfor\b|\band\b|$)", re.I)
EXPERIENCE = re.compile(r"(\d{1,2})\+?\s*(?:or more\s*)?years?(?:\s+of)?\s+(?:relevant\s+|professional\s+|work\s+|industry\s+)?experience", re.I)
DEGREE = re.compile(r"\b(bachelor'?s?|master'?s?|ph\.?d|doctorate|b\.?tech|m\.?tech|bsc|msc)\b", re.I)


def degree_level(s: str):
    s = s.lower()
    if re.search(r"ph\.?d|doctorate", s):
        return "DOCTORATE"
    if re.search(r"master|m\.?tech|msc", s):
        return "MASTER"
    if re.search(r"bachelor|b\.?tech|bsc", s):
        return "BACHELOR"
    return None


def detect_gates(line: str) -> list:
    gates = []
    low = line.lower()
    if "japanese" in low or "jlpt" in low:
        for m in re.finditer(r"\bN([1-5])\b", line):
            gates.append(HardGate(kind="LANGUAGE", params={"language": "japanese", "level": f"N{m.group(1)}"}))
            break
    for m in LANG_CEFR.finditer(line):
        gates.append(HardGate(kind="LANGUAGE", params={"language": m.group(1).lower(), "level": m.group(2).upper()}))
    years, op = [], "in"
    ma = GRAD_A.search(line)
    if ma:
        seg = ma.group(1)
        years = [int(y) for y in re.findall(r"\b(20\d{2})\b", seg)]
        sl = seg.lower()
        if years:
            if "between" in sl and len(years) == 2:
                op = "range"
            elif re.search(r"or later|and later|onward|or after|after", sl):
                op = "gte"
            elif re.search(r"or earlier|by |before|no later", sl):
                op = "lte"
    else:
        mb = GRAD_B.search(line)
        if mb:
            years = [int(mb.group(1) or mb.group(2))]
    if years:
        gates.append(HardGate(kind="GRADUATION", params={"op": op, "years": years}))
    if NO_SPONSOR.search(line):
        gates.append(HardGate(kind="VISA", params={"sponsorship": "NOT_AVAILABLE"}))
    mw = WORK_AUTH.search(line)
    if mw:
        gates.append(HardGate(kind="WORK_AUTH", params={"country": mw.group(1).strip().lower()}))
    me = EXPERIENCE.search(line)
    if me:
        gates.append(HardGate(kind="EXPERIENCE", params={"min_years": float(me.group(1))}))
    md = DEGREE.search(line)
    if md:
        lvl = degree_level(md.group(1))
        if lvl:
            gates.append(HardGate(kind="DEGREE", params={"level": lvl}))
    return gates


def _header_level(line: str):
    s = line.strip().rstrip(":").lower()
    if BULLET.match(line) or len(s) > 60 or not s or s.endswith("."):
        return None
    if any(k in s for k in PREFERRED_HDR):
        return Level.PREFERRED
    if any(k in s for k in OTHER_HDR):
        return "OTHER"
    if any(k in s for k in MANDATORY_HDR):
        return Level.MANDATORY
    return None


def extract_requirements(text: str) -> list:
    reqs, section, pos, n = [], None, 0, 0
    for raw in text.split("\n"):
        start = pos
        pos += len(raw) + 1
        line = raw.strip()
        if len(line) < 3:
            continue
        hdr = _header_level(raw)
        if hdr is not None:
            section = hdr
            continue
        is_bullet = bool(BULLET.match(raw))
        gates = detect_gates(line)
        inline = (Level.PREFERRED if INLINE_PREFERRED.search(line)
                  else Level.MANDATORY if INLINE_MANDATORY.search(line) else None)
        in_req_section = section in (Level.MANDATORY, Level.PREFERRED)
        if not (in_req_section or gates or inline or (is_bullet and section is None)):
            continue
        if section == "OTHER" and not (gates or inline):
            continue
        level = inline or (section if in_req_section else Level.UNCLEAR)
        skills = sorted(find_skills(line))
        if not (skills or gates or in_req_section or inline):
            continue
        n += 1
        off = raw.index(line[0]) if line else 0
        reqs.append(Requirement(
            id=f"REQ-{n:03d}", text=BULLET.sub("", line, count=1), level=level, skills=skills, gates=gates,
            span=Span(start=start + off, end=start + off + len(line), quote=line[:300])))
    return reqs
