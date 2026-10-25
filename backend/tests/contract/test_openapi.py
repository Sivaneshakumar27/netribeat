"""The committed docs/openapi.json must match the app, and the required endpoints exist."""

from __future__ import annotations

import json

from scripts.export_openapi import OUT, render

REQUIRED = {
    ("post", "/api/v1/auth/register"),
    ("post", "/api/v1/auth/verify-email"),
    ("post", "/api/v1/auth/resend-verification"),
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/forgot-password"),
    ("post", "/api/v1/auth/verify-reset-otp"),
    ("post", "/api/v1/auth/reset-password"),
    ("post", "/api/v1/auth/logout"),
    ("get", "/api/v1/auth/me"),
    ("post", "/api/v1/auth/refresh"),
    ("get", "/api/v1/health"),
}


def test_committed_openapi_is_up_to_date() -> None:
    assert OUT.exists(), "run: uv run python scripts/export_openapi.py"
    assert OUT.read_text(encoding="utf-8") == render(), (
        "docs/openapi.json is stale; run: uv run python scripts/export_openapi.py"
    )


def test_required_endpoints_present() -> None:
    spec = json.loads(render())
    have = {(m, p) for p, ops in spec["paths"].items() for m in ops}
    assert have >= REQUIRED


def test_every_operation_documents_error_schema() -> None:
    spec = json.loads(render())
    for path, ops in spec["paths"].items():
        if path.startswith("/api/v1/health"):
            continue
        for method, op in ops.items():
            errors = [c for c in op["responses"] if c.startswith(("4", "5"))]
            assert errors, f"{method} {path} documents no error responses"


def test_no_athlete_terminology_remains() -> None:
    assert "athlete" not in render().lower()
