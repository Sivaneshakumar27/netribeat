from __future__ import annotations

import httpx

from netribeat.config import Settings


async def test_security_headers_present(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/health")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in h["content-security-policy"]
    assert "x-request-id" in h
    assert "strict-transport-security" not in h  # only in production


async def test_auth_responses_are_not_cached(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/v1/auth/forgot-password", json={"email": "a@example.org"})
    assert r.headers["cache-control"] == "no-store"


async def test_oversized_body_is_413(client: httpx.AsyncClient, settings: Settings) -> None:
    big = "x" * (settings.max_json_body_bytes + 1)
    r = await client.post(
        "/api/v1/auth/login", content=big, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413
    assert r.json()["code"] == "payload_too_large"


async def test_unknown_route_uses_error_schema(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json() == {"code": "not_found", "message": "Not found"}


async def test_malformed_json_is_400_not_500(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/login", content="{not json", headers={"content-type": "application/json"}
    )
    assert r.status_code == 400 and r.json()["code"] == "validation_error"


async def test_cors_allows_only_configured_origin(client: httpx.AsyncClient) -> None:
    pre = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-requested-with",
    }
    ok = await client.options(
        "/api/v1/auth/refresh", headers={**pre, "Origin": "http://localhost:5173"}
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = await client.options(
        "/api/v1/auth/refresh", headers={**pre, "Origin": "https://evil.example"}
    )
    assert "access-control-allow-origin" not in bad.headers


async def test_sql_injection_in_email_is_just_invalid(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/login", json={"email": "' OR 1=1 --@x.org", "password": "x"}
    )
    assert r.status_code in (400, 401)


async def test_docs_hidden_in_production() -> None:
    from netribeat.config import EmailBackend, Environment, JobBackend
    from netribeat.main import create_app
    from tests.conftest import make_settings

    prod = make_settings(
        environment=Environment.PRODUCTION,
        cookie_secure=True,
        email_backend=EmailBackend.SMTP,
        smtp_host="smtp.example.org",
        job_backend=JobBackend.ARQ,
        cors_origins=["https://app.example.org"],
        frontend_base_url="https://app.example.org",
    )
    app = create_app(prod)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        for path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
            assert (await c.get(path)).status_code == 404
        r = await c.get("/api/v1/health")
        assert "max-age=63072000" in r.headers["strict-transport-security"]


async def test_docs_available_in_development(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/openapi.json")).status_code == 200
