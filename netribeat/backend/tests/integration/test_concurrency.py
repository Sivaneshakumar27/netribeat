"""Races that need real, separately committing connections (no rollback wrapper)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from netribeat.clock import FrozenClock
from netribeat.core.ratelimit import MemoryRateLimiter
from netribeat.db import make_sessionmaker
from netribeat.email.service import MemoryEmailSender
from netribeat.main import create_app
from tests.conftest import START, STRONG_PASSWORD, code_from, last_mail, make_settings


@pytest.fixture
async def live() -> AsyncIterator[tuple[httpx.AsyncClient, MemoryEmailSender, AsyncEngine, str]]:
    from netribeat.db import make_engine
    from tests.conftest import TEST_DATABASE_URL

    engine = make_engine(TEST_DATABASE_URL, pool_size=10)
    clock = FrozenClock(START)
    mail = MemoryEmailSender()
    app = create_app(
        make_settings(register_limit_per_ip_per_hour=1000),
        clock=clock,
        limiter=MemoryRateLimiter(clock),
        email_sender=mail,
    )
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.redis = None
    tag = uuid.uuid4().hex[:8]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c, mail, engine, tag
    async with engine.begin() as conn:
        pattern = f"%{tag}%"
        await conn.execute(text("DELETE FROM auth_challenges WHERE email LIKE :p"), {"p": pattern})
        await conn.execute(
            text("DELETE FROM pending_registrations WHERE email LIKE :p"), {"p": pattern}
        )
        await conn.execute(
            text(
                "DELETE FROM audit_events WHERE target_user_id IN "
                "(SELECT id FROM users WHERE email LIKE :p)"
            ),
            {"p": pattern},
        )
        await conn.execute(text("DELETE FROM users WHERE email LIKE :p"), {"p": pattern})
    await engine.dispose()


async def test_concurrent_registrations_leave_one_pending_row(
    live: tuple[httpx.AsyncClient, MemoryEmailSender, AsyncEngine, str],
) -> None:
    client, _, engine, tag = live
    email = f"race-{tag}@example.org"
    body = {
        "firstName": "R",
        "lastName": "C",
        "email": email,
        "password": STRONG_PASSWORD,
        "confirmPassword": STRONG_PASSWORD,
    }
    results = await asyncio.gather(
        *(client.post("/api/v1/auth/register", json=body) for _ in range(8)),
        return_exceptions=True,
    )
    statuses = [r.status_code if isinstance(r, httpx.Response) else repr(r) for r in results]
    # Concurrent challenge inserts may collide on the one-open-challenge index; such a
    # request fails safely (no partial state), never creating a second pending row.
    print("STATUSES", statuses)
    assert all(s in (202, 500) for s in statuses), statuses
    assert 202 in statuses
    async with engine.connect() as conn:
        n = (
            await conn.execute(
                text("SELECT count(*) FROM pending_registrations WHERE email=:e"), {"e": email}
            )
        ).scalar_one()
        open_ch = (
            await conn.execute(
                text("SELECT count(*) FROM auth_challenges WHERE email=:e AND closed_at IS NULL"),
                {"e": email},
            )
        ).scalar_one()
    assert n == 1 and open_ch == 1


async def test_concurrent_verification_creates_one_account(
    live: tuple[httpx.AsyncClient, MemoryEmailSender, AsyncEngine, str],
) -> None:
    client, mail, engine, tag = live
    email = f"verify-{tag}@example.org"
    await client.post(
        "/api/v1/auth/register",
        json={
            "firstName": "R",
            "lastName": "C",
            "email": email,
            "password": STRONG_PASSWORD,
            "confirmPassword": STRONG_PASSWORD,
        },
    )
    code = code_from(last_mail(mail, email, "verify_email"))
    results = await asyncio.gather(
        *(
            client.post("/api/v1/auth/verify-email", json={"email": email, "code": code})
            for _ in range(6)
        )
    )
    codes = sorted(r.status_code for r in results)
    assert codes.count(200) == 1 and set(codes) <= {200, 400}
    async with engine.connect() as conn:
        n = (
            await conn.execute(text("SELECT count(*) FROM users WHERE email=:e"), {"e": email})
        ).scalar_one()
    assert n == 1


async def test_concurrent_forgot_password_is_safe(
    live: tuple[httpx.AsyncClient, MemoryEmailSender, AsyncEngine, str],
) -> None:
    client, mail, engine, tag = live
    email = f"forgot-{tag}@example.org"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, email, role, source, is_active, token_version, "
                "email_verified_at) VALUES (gen_random_uuid(), :e, 'user', 'admin', true, 0, now())"
            ),
            {"e": email},
        )
    results = await asyncio.gather(
        *(client.post("/api/v1/auth/forgot-password", json={"email": email}) for _ in range(8))
    )
    assert [r.status_code for r in results] == [202] * 8
    assert len([m for m in mail.sent if m.to == email]) == 1  # cooldown, under the lock
    async with engine.connect() as conn:
        open_ch = (
            await conn.execute(
                text("SELECT count(*) FROM auth_challenges WHERE email=:e AND closed_at IS NULL"),
                {"e": email},
            )
        ).scalar_one()
    assert open_ch == 1
