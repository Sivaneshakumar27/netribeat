from __future__ import annotations

import pytest
from pydantic import ValidationError

from netribeat.config import EmailBackend, Environment, JobBackend
from tests.conftest import make_settings


def test_short_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET must be at least"):
        make_settings(jwt_secret="too-short")


def test_identical_secrets_are_rejected() -> None:
    same = "k" * 40
    with pytest.raises(ValidationError, match="must be different"):
        make_settings(jwt_secret=same, otp_pepper=same)


def test_password_minimum_cannot_go_below_eight() -> None:
    with pytest.raises(ValidationError):
        make_settings(password_min_length=7)


def test_production_refuses_dev_settings() -> None:
    with pytest.raises(ValidationError) as info:
        make_settings(
            environment=Environment.PRODUCTION,
            cookie_secure=False,
            email_backend=EmailBackend.CONSOLE,
            cors_origins=["*"],
            frontend_base_url="http://x",
        )
    text = str(info.value)
    for fragment in ("COOKIE_SECURE", "EMAIL_BACKEND", "'*'", "https"):
        assert fragment in text


def test_production_accepts_safe_settings() -> None:
    s = make_settings(
        environment=Environment.PRODUCTION,
        cookie_secure=True,
        job_backend=JobBackend.ARQ,
        email_backend=EmailBackend.SMTP,
        smtp_host="smtp.example.org",
        cors_origins=["https://app.example.org"],
        frontend_base_url="https://app.example.org",
    )
    assert s.is_production


def test_cors_origins_accept_comma_list() -> None:
    s = make_settings(cors_origins="https://a.example, https://b.example")
    assert s.cors_origins == ["https://a.example", "https://b.example"]


@pytest.mark.parametrize(
    "raw",
    [
        "http://localhost:5173, https://app.example.org",
        '["http://localhost:5173", "https://app.example.org"]',
    ],
)
def test_cors_origins_from_real_environment(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    from netribeat.config import Settings

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("JWT_SECRET", "j" * 40)
    monkeypatch.setenv("OTP_PEPPER", "p" * 40)
    monkeypatch.setenv("CORS_ORIGINS", raw)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.cors_origins == ["http://localhost:5173", "https://app.example.org"]


def test_production_requires_durable_jobs() -> None:
    with pytest.raises(ValidationError, match="JOB_BACKEND must be arq"):
        make_settings(
            environment=Environment.PRODUCTION,
            cookie_secure=True,
            email_backend=EmailBackend.SMTP,
            smtp_host="smtp.example.org",
            cors_origins=["https://app.example.org"],
            frontend_base_url="https://app.example.org",
        )
