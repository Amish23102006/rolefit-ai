"""Strict Pydantic schemas. extra='forbid' everywhere: malformed/extra fields are rejected."""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


DISCLAIMER = ("This score measures readiness under RoleFit AI's documented rubric. It is not an employer ATS "
              "score and does not guarantee screening, assessment, interview or selection.")


class Level(str, Enum):
    MANDATORY = "MANDATORY"
    PREFERRED = "PREFERRED"
    UNCLEAR = "UNCLEAR"


class GateStatus(str, Enum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    SOFT_MISMATCH = "SOFT_MISMATCH"


class Verification(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    CANDIDATE_APPROVED = "CANDIDATE_APPROVED"
    VERIFIED = "VERIFIED"


class EvidenceKind(str, Enum):
    PROJECT = "PROJECT"
    EDUCATION = "EDUCATION"
    WORK = "WORK"
    CERTIFICATE = "CERTIFICATE"
    ASSESSMENT = "ASSESSMENT"
    OTHER = "OTHER"


class Span(Strict):
    start: int
    end: int
    quote: str


class HardGate(Strict):
    kind: str  # LANGUAGE | GRADUATION | VISA | WORK_AUTH | DEGREE | EXPERIENCE
    params: dict


class Requirement(Strict):
    id: str
    text: str
    level: Level
    skills: list[str] = []
    gates: list[HardGate] = []
    span: Span


class Consents(Strict):
    parsing: bool = False
    job_discovery: bool = False
    llm_processing: bool = False
    analytics: bool = False
    model_improvement: bool = False  # default OFF: no training on user data


class Profile(Strict):
    degree: Optional[str] = Field(None, max_length=80)
    field_of_study: Optional[str] = Field(None, max_length=80)
    graduation_year: Optional[int] = Field(None, ge=1990, le=2100)
    experience_years: Optional[float] = Field(None, ge=0, le=60)
    languages: dict[str, str] = Field(default_factory=dict)  # {"japanese": "N5"} (self-declared)
    work_authorizations: list[str] = Field(default_factory=list)
    needs_sponsorship: Optional[bool] = None
    countries: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list, max_length=20)  # e.g. "machine learning", "data scientist"
    early_career_only: bool = True  # alerts: internships / graduate / entry-level only
    email_alerts: bool = False  # email me when new alerts are found (needs SMTP configured on the server)
    retention_days: int = Field(365, ge=1, le=3650)
    consents: Consents = Field(default_factory=Consents)


class EvidenceIn(Strict):
    kind: EvidenceKind
    title: str = Field(max_length=120)
    claim_text: str = Field(min_length=3, max_length=500)
    skills: list[str] = Field(default_factory=list, max_length=30)
    source_ref: Optional[str] = Field(None, max_length=300)  # URL or document id
    attributes: dict[str, str] = Field(default_factory=dict)


class JobIn(Strict):
    title: str = Field(max_length=120)
    company: str = Field(max_length=120)
    description_text: str = Field(min_length=20, max_length=20000)
    official_url: Optional[str] = Field(None, max_length=500)
    last_checked: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ScoreIn(Strict):
    resume_document_id: Optional[str] = None


class ResumeIn(Strict):
    acknowledge_mismatch: bool = False


class BulletEditIn(Strict):
    text: str = Field(min_length=3, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class JobFetchIn(Strict):
    url: str = Field(max_length=500)
    title: Optional[str] = Field(None, max_length=120)
    company: str = Field(max_length=120)


class GapIn(Strict):
    deadline: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class PracticeMode(str, Enum):
    MIXED = "mixed"
    TECHNICAL = "technical"
    PROJECT = "project"
    BEHAVIOURAL = "behavioural"
    JAPAN = "japan"


class PracticeIn(Strict):
    mode: PracticeMode = PracticeMode.MIXED
    count: int = Field(8, ge=1, le=20)
    live_assessment_active: bool = False


class CompanyIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    industry: Optional[str] = Field(None, max_length=80)
    country: Optional[str] = Field(None, max_length=60)
    careers_url: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=300)


class Stage(str, Enum):
    PLANNED = "PLANNED"
    APPLIED = "APPLIED"
    ONLINE_TEST = "ONLINE_TEST"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationIn(Strict):
    job_id: str = Field(max_length=64)
    resume_id: Optional[str] = Field(None, max_length=64)
    stage: Stage = Stage.PLANNED
    deadline: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    next_action: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=1000)


class ApplicationUpdate(Strict):
    stage: Optional[Stage] = None
    deadline: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    next_action: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=1000)


class FeedIn(Strict):
    url: str = Field(max_length=300)
    label: Optional[str] = Field(None, max_length=80)


class ScanIn(Strict):
    url: str = Field(max_length=500)
    company: str = Field(max_length=120)
    max_jobs: int = Field(8, ge=1, le=10)
