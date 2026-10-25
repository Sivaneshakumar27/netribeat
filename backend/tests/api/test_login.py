from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.clock import FrozenClock
from netribeat.users.models import Role, UserSource
from tests.conftest import CSRF, STRONG_PASSWORD
from tests.factories import login, make_admin, make_user

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"


async def test_login_success_returns_token_user_and_cookie(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    user = await make_user(db, email="ada@example.org")
    r = await client.post(LOGIN, json={"email": " ADA@example.org", "password": STRONG_PASSWORD})
    assert r.status_code == 200
    data = r.json()
    assert data["user"]["id"] == str(user.id) and data["user"]["role"] == "user"
    assert data["token"] and data["expiresAt"]
    cookie = r.headers["set-cookie"]
    assert "nb_refresh=" in cookie and "HttpOnly" in cookie
    assert "samesite=strict" in cookie.lower() and "Path=/api/v1/auth" in cookie
    assert "expires" not in cookie.lower()  # not "remember": browser-session cookie
    assert r.headers["cache-control"] == "no-store"


async def test_login_remember_sets_persistent_cookie(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    r = await client.post(
        LOGIN, json={"email": "ada@example.org", "password": STRONG_PASSWORD, "remember": True}
    )
    assert "expires=" in r.headers["set-cookie"].lower()


async def test_secure_cookie_flag_when_configured(
    db: AsyncSession, client: httpx.AsyncClient
) -> None:
    client._transport.app.state.settings.cookie_secure = True  # type: ignore[attr-defined]
    await make_user(db, email="ada@example.org")
    r = await client.post(LOGIN, json={"email": "ada@example.org", "password": STRONG_PASSWORD})
    assert "Secure" in r.headers["set-cookie"]


@pytest.mark.parametrize(
    "case", ["unknown", "wrong_password", "disabled", "unverified", "no_password", "admin_mode"]
)
async def test_every_login_failure_has_identical_401(
    case: str, client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="real@example.org")
    await make_user(db, email="disabled@example.org", active=False)
    await make_user(db, email="unverified@example.org", verified=False)
    await make_user(db, email="nopw@example.org", password=None, source=UserSource.UPLOAD)
    email, password, mode = {
        "unknown": ("ghost@example.org", STRONG_PASSWORD, "user"),
        "wrong_password": ("real@example.org", "not the password at all", "user"),
        "disabled": ("disabled@example.org", STRONG_PASSWORD, "user"),
        "unverified": ("unverified@example.org", STRONG_PASSWORD, "user"),
        "no_password": ("nopw@example.org", STRONG_PASSWORD, "user"),
        "admin_mode": ("real@example.org", STRONG_PASSWORD, "admin"),
    }[case]
    r = await client.post(LOGIN, json={"email": email, "password": password, "mode": mode})
    assert r.status_code == 401
    assert r.json() == {"code": "invalid_credentials", "message": "Email or password is incorrect"}
    assert "set-cookie" not in r.headers


async def test_admin_mode_login_for_admin(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_admin(db, email="boss@example.org")
    headers = await login(client, "boss@example.org", mode="admin")
    assert (await client.get(ME, headers=headers)).json()["role"] == "admin"


async def test_login_validation_messages(client: httpx.AsyncClient) -> None:
    r = await client.post(LOGIN, json={"email": "nope"})
    assert r.status_code == 400
    assert r.json()["fields"] == {
        "email": "Enter a valid email address, like name@institute.org",
        "password": "Enter your password",
    }


async def test_per_email_failure_limit(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession, clock: FrozenClock
) -> None:
    await make_user(db, email="ada@example.org")
    bad = {"email": "ada@example.org", "password": "wrong wrong wrong"}
    for i in range(10):  # from different IPs: only the per-email counter trips
        async with client_factory(f"198.51.100.{i}") as c:
            assert (await c.post(LOGIN, json=bad)).status_code == 401
    async with client_factory("198.51.100.200") as c:
        good = {"email": "ada@example.org", "password": STRONG_PASSWORD}
        r = await c.post(LOGIN, json=good)
        assert r.status_code == 429  # even the right password is refused while locked
        clock.advance(minutes=15, seconds=1)
        assert (await c.post(LOGIN, json=good)).status_code == 200


async def test_per_ip_failure_limit(client: httpx.AsyncClient, db: AsyncSession) -> None:
    for i in range(30):
        r = await client.post(LOGIN, json={"email": f"x{i}@example.org", "password": "nope nope"})
        assert r.status_code == 401
    r = await client.post(LOGIN, json={"email": "y@example.org", "password": "nope nope"})
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"


async def test_successful_login_resets_email_counter(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    for _ in range(9):
        await client.post(LOGIN, json={"email": "ada@example.org", "password": "wrong one here"})
    await login(client, "ada@example.org")
    for _ in range(9):
        r = await client.post(LOGIN, json={"email": "ada@example.org", "password": "wrong again"})
        assert r.status_code == 401


@pytest.mark.parametrize(
    "header",
    ["", "Bearer", "Bearer garbage", "Basic abc", "Bearer a.b.c"],
)
async def test_me_rejects_bad_tokens(client: httpx.AsyncClient, header: str) -> None:
    r = await client.get(ME, headers={"Authorization": header} if header else {})
    assert r.status_code == 401 and r.json()["code"] == "unauthorized"


async def test_access_token_expires(
    client: httpx.AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    await make_user(db, email="ada@example.org")
    headers = await login(client, "ada@example.org")
    clock.advance(minutes=14)
    assert (await client.get(ME, headers=headers)).status_code == 200
    clock.advance(minutes=1)
    assert (await client.get(ME, headers=headers)).status_code == 401


async def test_role_comes_from_database_each_request(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    user = await make_user(db, email="ada@example.org")
    headers = await login(client, "ada@example.org")
    user.role = Role.ADMIN  # changed directly, token untouched (no version bump)
    await db.commit()
    assert (await client.get(ME, headers=headers)).json()["role"] == "admin"


async def test_token_version_bump_invalidates_tokens(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    user = await make_user(db, email="ada@example.org")
    headers = await login(client, "ada@example.org")
    user.token_version += 1
    await db.commit()
    assert (await client.get(ME, headers=headers)).status_code == 401


async def test_refresh_rotates_cookie_and_old_cookie_is_reuse(
    client: httpx.AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    await make_user(db, email="ada@example.org")
    await login(client, "ada@example.org")
    old = client.cookies.get("nb_refresh")
    r = await client.post(REFRESH, headers=CSRF)
    assert r.status_code == 200
    new = client.cookies.get("nb_refresh")
    assert new and new != old
    assert (
        await client.get(ME, headers={"Authorization": f"Bearer {r.json()['token']}"})
    ).status_code == 200

    # Replaying the rotated-out cookie after the grace window = theft → session revoked.
    clock.advance(seconds=30)
    client.cookies.set("nb_refresh", old or "", path="/api/v1/auth")
    assert (await client.post(REFRESH, headers=CSRF)).status_code == 401
    client.cookies.set("nb_refresh", new, path="/api/v1/auth")
    assert (await client.post(REFRESH, headers=CSRF)).status_code == 401


async def test_concurrent_refresh_within_grace_does_not_sign_out(
    client: httpx.AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    await make_user(db, email="ada@example.org")
    await login(client, "ada@example.org")
    old = client.cookies.get("nb_refresh") or ""
    assert (await client.post(REFRESH, headers=CSRF)).status_code == 200
    new = client.cookies.get("nb_refresh") or ""
    clock.advance(seconds=5)
    client.cookies.set("nb_refresh", old, path="/api/v1/auth")
    r = await client.post(REFRESH, headers=CSRF)  # the "other tab"
    assert r.status_code == 200 and "set-cookie" not in r.headers
    client.cookies.set("nb_refresh", new, path="/api/v1/auth")
    assert (await client.post(REFRESH, headers=CSRF)).status_code == 200


async def test_refresh_requires_csrf_header(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="ada@example.org")
    await login(client, "ada@example.org")
    r = await client.post(REFRESH)
    assert r.status_code == 403 and r.json()["code"] == "csrf_failed"


async def test_refresh_rejects_foreign_origin(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="ada@example.org")
    await login(client, "ada@example.org")
    r = await client.post(REFRESH, headers={**CSRF, "Origin": "https://evil.example"})
    assert r.status_code == 403


async def test_refresh_without_cookie_is_401(client: httpx.AsyncClient) -> None:
    assert (await client.post(REFRESH, headers=CSRF)).status_code == 401


async def test_session_without_remember_ends_after_12_hours(
    client: httpx.AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    await make_user(db, email="ada@example.org")
    await login(client, "ada@example.org")
    clock.advance(hours=11, minutes=59)
    assert (await client.post(REFRESH, headers=CSRF)).status_code == 200
    clock.advance(minutes=2)
    assert (await client.post(REFRESH, headers=CSRF)).status_code == 401


async def test_remembered_session_lasts_30_days(
    client: httpx.AsyncClient, db: AsyncSession, clock: FrozenClock
) -> None:
    await make_user(db, email="ada@example.org")
    await login(client, "ada@example.org", remember=True)
    clock.advance(days=29)
    assert (await client.post(REFRESH, headers=CSRF)).status_code == 200
    clock.advance(days=1, seconds=1)
    assert (await client.post(REFRESH, headers=CSRF)).status_code == 401


async def test_logout_revokes_access_token_immediately(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    headers = await login(client, "ada@example.org")
    r = await client.post(LOGOUT, headers={**headers, **CSRF})
    assert r.status_code == 204
    assert 'nb_refresh=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    assert (await client.get(ME, headers=headers)).status_code == 401
    assert (await client.post(REFRESH, headers=CSRF)).status_code == 401


async def test_logout_with_only_cookie(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="ada@example.org")
    headers = await login(client, "ada@example.org")
    assert (await client.post(LOGOUT, headers=CSRF)).status_code == 204
    assert (await client.get(ME, headers=headers)).status_code == 401


async def test_logout_one_device_keeps_other(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    async with client_factory("192.0.2.1") as laptop, client_factory("192.0.2.2") as phone:
        h1 = await login(laptop, "ada@example.org")
        h2 = await login(phone, "ada@example.org")
        await laptop.post(LOGOUT, headers={**h1, **CSRF})
        assert (await laptop.get(ME, headers=h1)).status_code == 401
        assert (await phone.get(ME, headers=h2)).status_code == 200


async def test_disabled_user_session_is_dead(client: httpx.AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db, email="ada@example.org")
    headers = await login(client, "ada@example.org")
    user.is_active = False
    await db.commit()
    assert (await client.get(ME, headers=headers)).status_code == 401
    assert (await client.post(REFRESH, headers=CSRF)).status_code == 401
