"""Settings. Secrets come from the environment / secret manager, never from source."""
import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("rolefit.config")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv_file(path: Path = PROJECT_ROOT / ".env") -> bool:
    """Load .env for local runs. Real environment variables always win; never logs values."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    return load_dotenv(path, override=False)


@dataclass
class Settings:
    db_path: str = "rolefit.db"
    jwt_secret: str = ""
    jwt_ttl_minutes: int = 30
    max_upload_bytes: int = 5 * 1024 * 1024
    max_request_bytes: int = 6 * 1024 * 1024
    # Curated example allowlist - edit to your own vetted official career-site domains.
    allowed_job_domains: tuple = ("boards.greenhouse.io", "jobs.lever.co")
    resolve_dns: bool = True
    # Rate limits (count, per window seconds)
    login_per_minute_ip: int = 30
    login_fail_lockout: int = 5
    register_per_hour_ip: int = 10
    upload_per_hour: int = 10
    job_per_hour: int = 30
    fetch_per_hour: int = 10
    scan_per_hour: int = 6
    fetch_max_bytes: int = 2 * 1024 * 1024
    fetch_timeout: float = 10.0
    practice_per_hour: int = 30
    discovery_interval_hours: float = 0.0  # 0 = scheduler off (tests); from_env defaults to 6
    discovery_refresh_per_hour: int = 6
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = field(default="", repr=False)
    smtp_from: str = ""
    score_per_hour: int = 60
    api_per_minute: int = 240
    # LLM (optional). provider: none | groq | ollama. Key comes from env/secret manager only.
    llm_provider: str = "none"
    llm_api_key: str = field(default="", repr=False)
    llm_model: str = "openai/gpt-oss-120b"
    llm_tokens_per_day: int = 20000
    llm_backoff: float = 0.5

    @classmethod
    def from_env(cls, load_env_file: bool = True) -> "Settings":
        if load_env_file:
            load_dotenv_file()
        s = cls()
        s.db_path = os.getenv("ROLEFIT_DB_PATH", s.db_path)
        secret = os.getenv("ROLEFIT_JWT_SECRET", "")
        if secret.startswith("change-me"):
            raise RuntimeError("ROLEFIT_JWT_SECRET is still the .env.example placeholder. Generate one with: "
                               "python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
        if secret and len(secret) < 32:
            raise RuntimeError("ROLEFIT_JWT_SECRET must be at least 32 characters")
        if not secret:
            secret = secrets.token_urlsafe(48)
            log.warning("ROLEFIT_JWT_SECRET not set: using an ephemeral key (sessions reset on restart)")
        s.jwt_secret = secret
        s.llm_provider = os.getenv("ROLEFIT_LLM_PROVIDER", s.llm_provider).lower()
        s.llm_api_key = os.getenv("ROLEFIT_LLM_API_KEY", "")
        s.llm_model = os.getenv("ROLEFIT_LLM_MODEL", s.llm_model)
        s.discovery_interval_hours = float(os.getenv("ROLEFIT_DISCOVERY_INTERVAL_HOURS", "6"))
        s.smtp_host = os.getenv("ROLEFIT_SMTP_HOST", "")
        s.smtp_port = int(os.getenv("ROLEFIT_SMTP_PORT", "587"))
        s.smtp_user = os.getenv("ROLEFIT_SMTP_USER", "")
        s.smtp_password = os.getenv("ROLEFIT_SMTP_PASSWORD", "")
        s.smtp_from = os.getenv("ROLEFIT_SMTP_FROM", s.smtp_user)
        domains = os.getenv("ROLEFIT_ALLOWED_JOB_DOMAINS")
        if domains:
            s.allowed_job_domains = tuple(d.strip().lower() for d in domains.split(",") if d.strip())
        return s
