"""Every route needs a signed-in user unless it is on the explicit public list.
Adding a new route without auth makes this test fail."""

from __future__ import annotations

import re

import httpx
from fastapi import FastAPI

PUBLIC = {
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/ready"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/verify-email"),
    ("POST", "/api/v1/auth/resend-verification"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/forgot-password"),
    ("POST", "/api/v1/auth/verify-reset-otp"),
    ("POST", "/api/v1/auth/reset-password"),
    # Cookie-authenticated (refresh token) and CSRF-protected instead of bearer:
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/logout"),
}
UUID = "00000000-0000-4000-8000-000000000000"


def _routes(app: FastAPI) -> list[tuple[str, str]]:
    """Every operation the app exposes, from its OpenAPI document (public API; FastAPI's
    internal route objects changed shape across versions). No route sets
    include_in_schema=False, so the document lists everything."""
    out = [
        (method.upper(), path)
        for path, ops in app.openapi()["paths"].items()
        if path.startswith("/api/v1")
        for method in ops
    ]
    assert len(out) >= 20, "route discovery found too few operations; check this helper"
    return out


async def test_every_non_public_route_requires_auth(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    checked = 0
    for method, path in _routes(app):
        if (method, path) in PUBLIC:
            continue
        url = re.sub(r"\{[^}]+\}", UUID, path)
        r = await client.request(method, url, json={})
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"
        checked += 1
    assert checked >= 9


def test_public_list_has_no_stale_entries(app: FastAPI) -> None:
    assert set(PUBLIC) <= set(_routes(app))


async def test_registration_route_cannot_create_admin_by_any_field(
    client: httpx.AsyncClient,
) -> None:
    base = {
        "firstName": "A",
        "lastName": "B",
        "email": "x@example.org",
        "password": "correct horse battery staple",
        "confirmPassword": "correct horse battery staple",
    }
    for extra in (
        {"role": "admin"},
        {"role": "ADMIN"},
        {"isAdmin": True},
        {"is_admin": True},
        {"roles": ["admin"]},
    ):
        r = await client.post("/api/v1/auth/register", json={**base, **extra})
        assert r.status_code == 400, extra
