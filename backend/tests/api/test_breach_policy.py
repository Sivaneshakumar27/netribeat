from __future__ import annotations

import httpx
from fastapi import FastAPI

from tests.conftest import STRONG_PASSWORD


class AlwaysBreached:
    async def is_breached(self, password: str) -> bool:
        return True


async def test_breached_password_rejected_at_registration(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    app.state.breach_checker = AlwaysBreached()
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "firstName": "A",
            "lastName": "B",
            "email": "a@example.org",
            "password": STRONG_PASSWORD,
            "confirmPassword": STRONG_PASSWORD,
        },
    )
    assert r.status_code == 400
    assert "data breach" in r.json()["fields"]["password"]
