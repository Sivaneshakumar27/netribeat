"""Shared fixtures.

Tests run against a real PostgreSQL database (TEST_DATABASE_URL). The schema is built
with `alembic upgrade head` once per run, which also exercises the migrations. Each
test runs inside an outer transaction that is rolled back; services' commits become
savepoints (join_transaction_mode="create_savepoint"), so tests never see each other.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from netribeat.clock import FrozenClock
from netribeat.config import EmailBackend, Environment, Settings
from netribeat.core.ratelimit import MemoryRateLimiter
from netribeat.core.storage import MemoryStorage
from netribeat.db import make_engine
from netribeat.email.service import MemoryEmailSender, OutgoingEmail
from netribeat.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _test_database_url() -> str:
    """TEST_DATABASE_URL, or DATABASE_URL (env or backend/.env) with the database name
    replaced by `netribeat_test`. Tests drop and recreate the schema: never point this
    at a database whose data you need."""
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = os.environ.get("DATABASE_URL")
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not url and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"')
    if not url:
        raise RuntimeError("Set TEST_DATABASE_URL (or DATABASE_URL) to run the tests")
    base, _, _db = url.rpartition("/")
    return f"{base}/netribeat_test"


TEST_DATABASE_URL = _test_database_url()
START = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
CSRF = {"X-Requested-With": "NetriBeat"}
STRONG_PASSWORD = "correct horse battery staple"
OTHER_STRONG_PASSWORD = "violet kettle orbit 4219"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": Environment.TEST,
        "database_url": TEST_DATABASE_URL,
        "jwt_secret": secrets.token_urlsafe(48),
        "otp_pepper": secrets.token_urlsafe(48),
        "email_backend": EmailBackend.MEMORY,
        "cookie_secure": False,  # httpx sends cookies back over http://test only if not Secure
        "frontend_base_url": "http://localhost:5173",
        "cors_origins": ["http://localhost:5173"],
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def run_alembic(*args: str, url: str = TEST_DATABASE_URL) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": url}
    return subprocess.run(  # noqa: S603 — fixed argv
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    down = run_alembic("downgrade", "base")
    assert down.returncode == 0, down.stderr
    up = run_alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    eng = make_engine(TEST_DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()


@pytest.fixture
def maker(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


@pytest.fixture
async def db(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with maker() as session:
        yield session


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(START)


@pytest.fixture
def mail() -> MemoryEmailSender:
    return MemoryEmailSender()


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def app(
    settings: Settings,
    clock: FrozenClock,
    mail: MemoryEmailSender,
    maker: async_sessionmaker[AsyncSession],
) -> FastAPI:
    application = create_app(
        settings,
        clock=clock,
        limiter=MemoryRateLimiter(clock),
        email_sender=mail,
        storage=MemoryStorage(),
        inline_jobs_wait=True,  # analysis finishes before the upload request returns
    )
    application.state.sessionmaker = maker  # lifespan is not run in tests
    application.state.redis = None
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, client=("203.0.113.10", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def client_factory(app: FastAPI) -> Callable[[str], httpx.AsyncClient]:
    """A fresh client (own cookie jar) from a given IP, for multi-device / multi-IP tests."""

    def make(ip: str = "203.0.113.20") -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(ip, 50001)), base_url="http://test"
        )

    return make


CODE_RE = re.compile(r"^\s{4}(\d{6,10})\s*$", re.M)


def code_from(message: OutgoingEmail) -> str:
    match = CODE_RE.search(message.text)
    assert match, f"no code in {message.template}"
    return match.group(1)


def last_mail(mail: MemoryEmailSender, to: str, template: str) -> OutgoingEmail:
    matches = [m for m in mail.sent if m.to == to and m.template == template]
    assert matches, f"no {template} email to {to}; sent={[(m.to, m.template) for m in mail.sent]}"
    return matches[-1]


async def table_count(db: AsyncSession, table: str) -> int:
    allowed = {
        "users",
        "pending_registrations",
        "auth_challenges",
        "auth_sessions",
        "audit_events",
        "sessions",
        "session_files",
        "analysis_results",
    }
    assert table in allowed
    return int((await db.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())  # noqa: S608
