import json
import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

DEFAULT_SECRET_KEY = "change-this-secret-in-production"
# The one environment name allowed to run on the committed placeholder key.
LOCAL_ENVIRONMENT = "development"


class Settings(BaseSettings):
    app_name: str = "CEU Compliance & Certificate Automation Portal"
    environment: str = "development"
    secret_key: str = DEFAULT_SECRET_KEY
    access_token_expire_minutes: int = 480
    database_url: str = "postgresql+psycopg://ceu_user:ceu_password@localhost:5432/ceu_compliance"
    # Plain string so pydantic-settings never tries to JSON-decode it from the
    # environment; parsed into a list by the `cors_origins` property below.
    backend_cors_origins: str = "http://localhost:5173"
    storage_dir: Path = Path("storage")
    # Supabase Storage (durable object storage for uploads + certificate PDFs).
    # When all three are set, files are stored in the Supabase bucket (with the
    # local disk as a serving cache); otherwise plain local-disk storage is used.
    # The bucket MUST be private — it holds attendee PII and certificates, which
    # are only served through this API's authenticated endpoints.
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str | None = None
    certificate_issuer_name: str = "Continuing Education Compliance Team"
    email_delivery_mode: str = "log"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "certificates@example.com"
    # Resend HTTPS email API (used when EMAIL_DELIVERY_MODE=resend; works where
    # outbound SMTP is blocked, e.g. Render). resend_from must be a verified
    # sender/domain, or "onboarding@resend.dev" for test sends to your own email.
    resend_api_key: str | None = None
    resend_from: str = "CEU Portal <onboarding@resend.dev>"
    # Optional contact address shown in the do-not-reply footer of every
    # outgoing email ("Questions? Contact ...").
    reply_contact_email: str | None = None
    retention_years: int = 7
    public_frontend_url: str = "http://127.0.0.1:8080"
    # Abuse controls for the unauthenticated endpoints (public check-in, post
    # test, survey, certificate verification). Anyone who can read a printed QR
    # code can call these, so each caller gets a bounded budget per window.
    # Counted per client IP + the token/certificate number in the URL.
    public_rate_limit_enabled: bool = True
    public_rate_limit_window_seconds: int = 60
    public_rate_limit_lockout_seconds: int = 60
    # Writes (check-in / test / survey submissions): a real attendee submits
    # each form once or twice, so this is generous for humans and hostile to a
    # script filling the official CEU record.
    public_write_rate_limit: int = 20
    # Reads (certificate verification): an employer checking a handful of
    # certificates stays well under this; enumerating certificate numbers does
    # not.
    public_verify_rate_limit: int = 60
    # Password reset. Both endpoints are unauthenticated: "email me a link" is
    # an unauthenticated write (it sends mail and mints a credential), and
    # "here is my token" is an unauthenticated guess at one. A person resetting
    # their own password does it once; this budget is hostile to anything else.
    password_reset_rate_limit: int = 5
    # How long a reset link stays usable. Presenters log in roughly twice a
    # year and an admin may have to relay the link by phone, so a same-day
    # window is too short to be workable; a token that outlives the day it was
    # asked for is a standing credential.
    password_reset_ttl_hours: int = 24
    survey_ai_enabled: bool = False
    survey_ai_model: str = "claude-opus-4-8"
    anthropic_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        # Accept either a JSON array (["a","b"]) or a plain comma-separated
        # string (a,b) so both .env and host env-var conventions work.
        text = self.backend_cors_origins.strip()
        if text.startswith("["):
            return json.loads(text)
        return [origin.strip() for origin in text.split(",") if origin.strip()]

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def certificates_dir(self) -> Path:
        return self.storage_dir / "certificates"


def running_under_pytest() -> bool:
    """True while the test suite is running.

    The suite deliberately runs on the placeholder key (it signs throwaway
    tokens against an in-memory database), so the fail-closed check below has
    to let it through.
    """
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def enforce_secret_key(settings: "Settings") -> None:
    """Fail closed unless the deployment has its own SECRET_KEY.

    The placeholder key is committed to the repository, so anyone can forge an
    admin JWT against a deployment still using it. Only a local development box
    -- environment exactly "development" -- may run on it, and even then it
    warns loudly. Every other environment name (staging, preview, production,
    a typo) is rejected: a preview deploy signing real tokens with a public key
    is just as exploitable as production.
    """
    if settings.secret_key not in ("", DEFAULT_SECRET_KEY):
        return
    if running_under_pytest():
        return
    if settings.environment == LOCAL_ENVIRONMENT:
        logger.warning(
            "SECURITY: running with the committed placeholder SECRET_KEY. This is "
            "allowed only for local development (ENVIRONMENT=%s); anyone can forge "
            "an admin session against a deployment configured this way. Set a "
            "strong, unique SECRET_KEY before this reaches a shared host.",
            LOCAL_ENVIRONMENT,
        )
        return
    raise RuntimeError(
        f"SECRET_KEY is unset or still the committed placeholder while "
        f"ENVIRONMENT={settings.environment!r}. Set a strong, unique SECRET_KEY "
        f"environment variable (only ENVIRONMENT={LOCAL_ENVIRONMENT!r} may run "
        f"without one)."
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    enforce_secret_key(settings)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.certificates_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
