"""Evidence-only CV drafting + factuality enforcement. No free-text generation: every bullet is
derived from, and validated against, candidate-approved evidence."""
import html
import re
import uuid

from . import evidence as ev
from .skills import find_skills

_NUM = re.compile(r"\d+(?:[.,]\d+)?\s*%?")


def build_draft(requirements, evidence_items: list) -> list:
    matches = ev.match(requirements, evidence_items)
    chosen = {}
    for rid, items in matches.items():
        for e in items:
            chosen.setdefault(e["id"], (e, []))[1].append(rid)
    for e in ev.usable(evidence_items):
        if e["kind"] == "EDUCATION":
            chosen.setdefault(e["id"], (e, []))
    return [{"id": uuid.uuid4().hex[:12], "text": e["claim_text"], "evidence_ids": [e["id"]],
             "requirement_ids": rids, "kind": e["kind"], "approved": False} for e, rids in chosen.values()]


def validate_bullet(text: str, evidence_ids: list, evidence_by_id: dict) -> list:
    """Return a list of error strings (empty = valid)."""
    errors = []
    if not evidence_ids:
        return ["Bullet has no evidence reference"]
    src = []
    for i in evidence_ids:
        e = evidence_by_id.get(i)
        if e is None:
            errors.append(f"Unknown evidence id {i}")
        elif e["verification_status"] not in ev.USABLE:
            errors.append(f"Evidence {i} is not approved")
        else:
            src.append(e)
    if errors:
        return errors
    blob = " ".join(e["claim_text"] for e in src)
    allowed_nums = {n.strip() for n in _NUM.findall(blob)}
    for n in _NUM.findall(text):
        if n.strip() not in allowed_nums:
            errors.append(f"Number/metric '{n.strip()}' is not in the referenced evidence")
    allowed_skills = set().union(*(ev.evidence_skills(e) for e in src))
    for s in find_skills(text) - allowed_skills:
        errors.append(f"Skill '{s}' is not supported by the referenced evidence")
    return errors


def render(bullets: list, evidence_by_id: dict, approved: bool) -> str:
    sections = {"EDUCATION": "Education", "WORK": "Experience", "PROJECT": "Projects", "CERTIFICATE": "Certificates",
                "ASSESSMENT": "Assessments", "OTHER": "Other"}
    lines = [] if approved else ["**DRAFT - NOT APPROVED. Do not submit.**", ""]
    for kind, title in sections.items():
        bs = [b for b in bullets if b["kind"] == kind]
        if bs:
            lines += [f"## {title}"] + [f"- {html.escape(b['text'])}" for b in bs] + [""]
    skills = sorted(set().union(*(ev.evidence_skills(evidence_by_id[i]) for b in bullets for i in b["evidence_ids"] if i in evidence_by_id)) or [])
    if skills:
        lines += ["## Skills", ", ".join(html.escape(s) for s in skills)]
    return "\n".join(lines)
