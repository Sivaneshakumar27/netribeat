"""Run the whole account lifecycle and assert no password, OTP or token reaches the logs,
the audit table, or any stored column in plaintext."""

from __future__ import annotations

import logging

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.email.service import MemoryEmailSender
from netribeat.logging_config import REDACTED, KeyValueFormatter, RedactFilter
from tests.conftest import CSRF, OTHER_STRONG_PASSWORD, STRONG_PASSWORD, code_from, last_mail

EMAIL = "lifecycle@example.org"


async def test_lifecycle_leaks_nothing(
    client: httpx.AsyncClient,
    mail: MemoryEmailSender,
    db: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    secrets: list[str] = [STRONG_PASSWORD, OTHER_STRONG_PASSWORD]

    await client.post(
        "/api/v1/auth/register",
        json={
            "firstName": "Life",
            "lastName": "Cycle",
            "email": EMAIL,
            "password": STRONG_PASSWORD,
            "confirmPassword": STRONG_PASSWORD,
        },
    )
    code = code_from(last_mail(mail, EMAIL, "verify_email"))
    secrets.append(code)
    await client.post("/api/v1/auth/verify-email", json={"email": EMAIL, "code": code})
    r = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": STRONG_PASSWORD})
    token = r.json()["token"]
    secrets += [token, client.cookies.get("nb_refresh") or ""]
    await client.post("/api/v1/auth/refresh", headers=CSRF)
    secrets.append(client.cookies.get("nb_refresh") or "")
    await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": "wrong guess here"})
    await client.post("/api/v1/auth/forgot-password", json={"email": EMAIL})
    reset_code = code_from(last_mail(mail, EMAIL, "password_reset_code"))
    secrets.append(reset_code)
    rt = (
        await client.post(
            "/api/v1/auth/verify-reset-otp", json={"email": EMAIL, "code": reset_code}
        )
    ).json()["resetToken"]
    secrets.append(rt)
    await client.post(
        "/api/v1/auth/reset-password",
        json={
            "resetToken": rt,
            "password": OTHER_STRONG_PASSWORD,
            "confirmPassword": OTHER_STRONG_PASSWORD,
        },
    )

    logs = caplog.text + capsys.readouterr().out
    for s in filter(None, secrets):
        assert s not in logs

    dump = ""
    for table in (
        "users",
        "pending_registrations",
        "auth_challenges",
        "auth_sessions",
        "audit_events",
    ):
        rows = (await db.execute(text(f"SELECT * FROM {table}"))).all()  # noqa: S608
        dump += repr(rows)
    for s in filter(None, secrets):
        assert s not in dump
    audit = repr((await db.execute(text("SELECT details FROM audit_events"))).all())
    assert EMAIL not in audit
    stored = (await db.execute(text("SELECT password_hash FROM users"))).scalar_one()
    assert stored.startswith("$argon2id$")


def test_redact_filter_masks_sensitive_extras() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    record.password = "hunter2"
    record.reset_token = "abc"
    record.email = "a@b.c"
    record.user_id = "123"
    RedactFilter().filter(record)
    line = KeyValueFormatter().format(record)
    assert "hunter2" not in line and "abc" not in line and "a@b.c" not in line
    assert line.count(REDACTED) == 3 and "user_id=123" in line
