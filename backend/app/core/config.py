from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CEU Compliance & Certificate Automation Portal"
    environment: str = "development"
    secret_key: str = "change-this-secret-in-production"
    access_token_expire_minutes: int = 480
    database_url: str = "postgresql+psycopg://ceu_user:ceu_password@localhost:5432/ceu_compliance"
    backend_cors_origins: list[str | AnyHttpUrl] = ["http://localhost:5173"]
    storage_dir: Path = Path("storage")
    certificate_issuer_name: str = "Continuing Education Compliance Team"
    email_delivery_mode: str = "log"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "certificates@example.com"
    retention_years: int = 7
    public_frontend_url: str = "http://127.0.0.1:8080"
    survey_ai_enabled: bool = False
    survey_ai_model: str = "claude-opus-4-8"
    anthropic_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("backend_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def certificates_dir(self) -> Path:
        return self.storage_dir / "certificates"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.certificates_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
