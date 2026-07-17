import json
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET_KEY = "change-this-secret-in-production"


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


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment == "production" and settings.secret_key in ("", DEFAULT_SECRET_KEY):
        raise RuntimeError(
            "SECRET_KEY is unset or still the development placeholder. "
            "Set a strong, unique SECRET_KEY environment variable before running in production."
        )
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.certificates_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
