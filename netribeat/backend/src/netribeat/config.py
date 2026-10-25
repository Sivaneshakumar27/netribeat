"""Application settings, read only from environment variables (or a local .env file).

No secret has a usable default. In production (`ENVIRONMENT=production`) the
settings validator refuses to start with development-only options switched on.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class JobBackend(StrEnum):
    INLINE = "inline"  # analysis runs inside the API process (development only)
    ARQ = "arq"  # durable Redis queue + separate worker process (production)


class EmailBackend(StrEnum):
    CONSOLE = "console"  # prints mail to stdout; development only
    FILE = "file"  # writes .eml files to EMAIL_FILE_DIR; development only
    SMTP = "smtp"  # real delivery
    MEMORY = "memory"  # tests only


MIN_SECRET_LENGTH = 32
ABSOLUTE_MIN_PASSWORD_LENGTH = 8  # master prompt §6: never below 8


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Environment = Environment.DEVELOPMENT

    # --- infrastructure ---
    database_url: str = Field(description="postgresql+asyncpg://user:pass@host:5432/db")
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: Path = Path("./var/storage")

    # --- tokens ---
    jwt_secret: SecretStr
    otp_pepper: SecretStr = Field(description="HMAC key for OTP / reset-token hashes")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    session_hours_default: int = Field(default=12, ge=1, le=72)  # AUTH-2: remember=false
    session_days_remember: int = Field(default=30, ge=1, le=90)  # AUTH-2: remember=true

    # --- cookies / browser ---
    cookie_secure: bool = True
    cookie_domain: str | None = None
    # NoDecode: accept a plain comma-separated value from the environment (or a JSON list).
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    frontend_base_url: str = "http://localhost:5173"

    # --- password policy ---
    password_min_length: int = 12
    password_max_length: int = 128
    hibp_check_enabled: bool = False  # k-anonymity range API; needs outbound HTTPS

    # --- OTP / challenges ---
    otp_length: int = Field(default=6, ge=6, le=10)
    otp_ttl_minutes: int = Field(default=10, ge=2, le=60)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=10)
    otp_max_sends_per_hour: int = Field(default=3, ge=1)  # AUTH-4: 3 emails / address / hour
    reset_token_ttl_minutes: int = Field(default=10, ge=2, le=60)
    pending_registration_hours: int = Field(default=24, ge=1)

    # --- rate limits (fixed windows, counters in Redis) ---
    login_fail_limit_per_email: int = 10  # AUTH-2
    login_fail_limit_per_ip: int = 30  # AUTH-2
    login_window_minutes: int = 15
    forgot_limit_per_ip_per_hour: int = 10  # AUTH-4
    register_limit_per_ip_per_hour: int = 10
    otp_verify_limit_per_ip: int = 30
    otp_verify_window_minutes: int = 15

    # --- request limits ---
    max_json_body_bytes: int = 64 * 1024

    # --- email ---
    email_backend: EmailBackend = EmailBackend.CONSOLE
    email_from: str = "NetriBeat <no-reply@localhost>"
    email_file_dir: Path = Path("./var/mail")
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_seconds: float = 15.0

    # --- recordings ---
    job_backend: JobBackend = JobBackend.INLINE
    max_upload_file_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)  # 50 MB per file
    max_upload_files: int = Field(default=10, ge=1, le=50)
    analysis_timeout_seconds: int = Field(default=600, ge=30)

    # --- misc ---
    log_level: str = "INFO"
    # Interactive docs (/api/docs, /api/redoc, /api/openapi.json). Default: on except in
    # production. Set API_DOCS_ENABLED=true to force them on.
    api_docs_enabled: bool | None = None
    trust_proxy_headers: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [o.strip() for o in stripped.split(",") if o.strip()]
        return v

    @field_validator("password_min_length")
    @classmethod
    def _min_password(cls, v: int) -> int:
        if v < ABSOLUTE_MIN_PASSWORD_LENGTH:
            raise ValueError(f"password_min_length must be >= {ABSOLUTE_MIN_PASSWORD_LENGTH}")
        return v

    @model_validator(mode="after")
    def _check_secrets_and_production(self) -> Settings:
        for name in ("jwt_secret", "otp_pepper"):
            value: SecretStr = getattr(self, name)
            if len(value.get_secret_value()) < MIN_SECRET_LENGTH:
                raise ValueError(f"{name.upper()} must be at least {MIN_SECRET_LENGTH} characters")
        if self.jwt_secret.get_secret_value() == self.otp_pepper.get_secret_value():
            raise ValueError("JWT_SECRET and OTP_PEPPER must be different")
        if self.environment is Environment.PRODUCTION:
            problems: list[str] = []
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true")
            if self.email_backend is not EmailBackend.SMTP:
                problems.append("EMAIL_BACKEND must be smtp")
            if not self.cors_origins:
                problems.append("CORS_ORIGINS must list the frontend origin(s)")
            if any(o == "*" for o in self.cors_origins):
                problems.append("CORS_ORIGINS must not contain '*'")
            if self.job_backend is not JobBackend.ARQ:
                problems.append("JOB_BACKEND must be arq (durable background jobs)")
            if not self.frontend_base_url.startswith("https://"):
                problems.append("FRONTEND_BASE_URL must be https")
            if problems:
                raise ValueError("Unsafe production settings: " + "; ".join(problems))
        if self.email_backend is EmailBackend.SMTP and not self.smtp_host:
            raise ValueError("SMTP_HOST is required when EMAIL_BACKEND=smtp")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def docs_enabled(self) -> bool:
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return not self.is_production

    @property
    def max_upload_request_bytes(self) -> int:
        return self.max_upload_files * self.max_upload_file_bytes + 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
