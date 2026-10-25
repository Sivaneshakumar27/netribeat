"""Run the real lifespan (engine + Redis) and the readiness probe."""

from __future__ import annotations

import httpx
import pytest
from redis.asyncio import Redis

from netribeat.main import create_app
from tests.conftest import make_settings


async def _redis_up() -> bool:
    r = Redis.from_url("redis://localhost:6379/15")
    try:
        await r.ping()
        return True
    except Exception:
        return False
    finally:
        await r.aclose()


@pytest.mark.redis
async def test_ready_with_real_dependencies() -> None:
    if not await _redis_up():
        pytest.skip("Redis not available")
    app = create_app(make_settings(redis_url="redis://localhost:6379/15"))
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://t") as c,
    ):
        r = await c.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_ready_reports_unavailable_dependencies() -> None:
    app = create_app(
        make_settings(
            database_url="postgresql+asyncpg://nobody:x@127.0.0.1:1/none",
            redis_url="redis://127.0.0.1:1/0",
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://t") as c,
    ):
        r = await c.get("/api/v1/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"] == {"database": "unavailable", "redis": "unavailable"}
    assert "nobody" not in r.text  # no connection details leak


async def test_redis_outage_fails_closed_with_503() -> None:
    app = create_app(make_settings(redis_url="redis://127.0.0.1:1/0"))
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://t") as c,
    ):
        r = await c.post(
            "/api/v1/auth/login", json={"email": "a@example.org", "password": "whatever at all"}
        )
    assert r.status_code == 503
    assert r.json()["code"] == "service_unavailable"
