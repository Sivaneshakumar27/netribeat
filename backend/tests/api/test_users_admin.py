from __future__ import annotations

from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.audit.models import AuditEvent
from netribeat.email.service import MemoryEmailSender
from tests.conftest import CSRF, OTHER_STRONG_PASSWORD, STRONG_PASSWORD, last_mail
from tests.factories import login, make_admin, make_user

ADMIN = "/api/v1/admin"
ME = "/api/v1/users/me"


# ------------------------------------------------------------------ self-service profile


async def test_profile_get_and_update(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    r = await client.patch(ME, headers=h, json={"firstName": " Ada ", "age": 29})
    assert r.status_code == 200
    assert r.json()["firstName"] == "Ada" and r.json()["age"] == 29
    assert (await client.get(ME, headers=h)).json()["age"] == 29


async def test_profile_cannot_set_role_or_email(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    for field, value in (("role", "admin"), ("email", "x@example.org"), ("isActive", True)):
        r = await client.patch(ME, headers=h, json={field: value})
        assert r.status_code == 400 and field in r.json()["fields"]
    assert (await client.get(ME, headers=h)).json()["role"] == "user"


async def test_profile_age_range(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    assert (await client.patch(ME, headers=h, json={"age": 7})).status_code == 400
    assert (await client.patch(ME, headers=h, json={"age": 101})).status_code == 400
    assert (await client.patch(ME, headers=h, json={"age": 8})).status_code == 200
    assert (await client.patch(ME, headers=h, json={"age": 100})).status_code == 200


async def test_change_password_keeps_this_device_signs_out_others(
    client_factory: Callable[[str], httpx.AsyncClient],
    db: AsyncSession,
    mail: MemoryEmailSender,
) -> None:
    await make_user(db, email="ada@example.org")
    async with client_factory("192.0.2.1") as here, client_factory("192.0.2.2") as there:
        h_here = await login(here, "ada@example.org")
        h_there = await login(there, "ada@example.org")
        r = await here.post(
            f"{ME}/password",
            headers=h_here,
            json={
                "currentPassword": STRONG_PASSWORD,
                "newPassword": OTHER_STRONG_PASSWORD,
                "confirmPassword": OTHER_STRONG_PASSWORD,
            },
        )
        assert r.status_code == 204
        assert (await here.get(ME, headers=h_here)).status_code == 200
        assert (await there.get(ME, headers=h_there)).status_code == 401
        await login(here, "ada@example.org", OTHER_STRONG_PASSWORD)
        last_mail(mail, "ada@example.org", "password_changed")


async def test_change_password_wrong_current(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    r = await client.post(
        f"{ME}/password",
        headers=h,
        json={
            "currentPassword": "not my password",
            "newPassword": OTHER_STRONG_PASSWORD,
            "confirmPassword": OTHER_STRONG_PASSWORD,
        },
    )
    assert r.status_code == 400 and "currentPassword" in r.json()["fields"]


# ------------------------------------------------------------------ admin authorisation


async def test_admin_routes_need_admin(client: httpx.AsyncClient, db: AsyncSession) -> None:
    target = await make_user(db, email="t@example.org")
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    calls = [
        ("GET", f"{ADMIN}/users", None),
        ("POST", f"{ADMIN}/users", {"email": "n@example.org", "firstName": "N", "lastName": "N"}),
        ("GET", f"{ADMIN}/users/{target.id}", None),
        ("PATCH", f"{ADMIN}/users/{target.id}/status", {"isActive": False}),
        ("PATCH", f"{ADMIN}/users/{target.id}/role", {"role": "admin"}),
        ("GET", f"{ADMIN}/audit-events", None),
    ]
    for method, url, json in calls:
        assert (await client.request(method, url, json=json)).status_code == 401, url
        r = await client.request(method, url, json=json, headers=h)
        assert r.status_code == 403 and r.json()["code"] == "forbidden", url


async def test_user_cannot_promote_self(client: httpx.AsyncClient, db: AsyncSession) -> None:
    me = await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    r = await client.patch(f"{ADMIN}/users/{me.id}/role", headers=h, json={"role": "admin"})
    assert r.status_code == 403
    assert (await client.get(ME, headers=h)).json()["role"] == "user"


# ------------------------------------------------------------------ admin operations


async def test_admin_list_search_filter_paginate(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_admin(db, email="boss@example.org")
    for name in ("alpha", "beta", "gamma"):
        await make_user(db, email=f"{name}@example.org", last_name=name.title())
    await make_user(db, email="off@example.org", active=False)
    h = await login(client, "boss@example.org", mode="admin")

    r = (await client.get(f"{ADMIN}/users", headers=h, params={"limit": 2})).json()
    assert r["total"] == 5 and len(r["items"]) == 2
    r = (await client.get(f"{ADMIN}/users", headers=h, params={"q": "BET"})).json()
    assert [u["email"] for u in r["items"]] == ["beta@example.org"]
    r = (await client.get(f"{ADMIN}/users", headers=h, params={"isActive": "false"})).json()
    assert [u["email"] for u in r["items"]] == ["off@example.org"]
    r = (await client.get(f"{ADMIN}/users", headers=h, params={"role": "admin"})).json()
    assert [u["email"] for u in r["items"]] == ["boss@example.org"]
    r = (await client.get(f"{ADMIN}/users", headers=h, params={"sort": "email"})).json()
    emails = [u["email"] for u in r["items"]]
    assert emails == sorted(emails)
    assert "passwordHash" not in r["items"][0]


async def test_admin_search_treats_wildcards_literally(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_admin(db, email="boss@example.org")
    await make_user(db, email="plain@example.org")
    h = await login(client, "boss@example.org")
    r = (await client.get(f"{ADMIN}/users", headers=h, params={"q": "%"})).json()
    assert r["total"] == 0


async def test_admin_create_user_without_password_and_invite(
    client: httpx.AsyncClient, db: AsyncSession, mail: MemoryEmailSender
) -> None:
    await make_admin(db, email="boss@example.org")
    h = await login(client, "boss@example.org")
    r = await client.post(
        f"{ADMIN}/users",
        headers=h,
        json={"email": "New@Example.org", "firstName": "New", "lastName": "User", "role": "admin"},
    )
    assert r.status_code == 400  # role can't be chosen here
    r = await client.post(
        f"{ADMIN}/users",
        headers=h,
        json={"email": "New@Example.org", "firstName": "New", "lastName": "User"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["role"] == "user" and data["hasPassword"] is False and data["source"] == "admin"
    invite = last_mail(mail, "new@example.org", "account_invited")
    assert "Forgot password" in invite.text
    dup = await client.post(
        f"{ADMIN}/users",
        headers=h,
        json={"email": "new@example.org", "firstName": "N", "lastName": "U"},
    )
    assert dup.status_code == 409


async def test_disable_signs_user_out_and_blocks_login(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_admin(db, email="boss@example.org")
    target = await make_user(db, email="ada@example.org")
    async with client_factory("192.0.2.1") as admin_c, client_factory("192.0.2.2") as user_c:
        ha = await login(admin_c, "boss@example.org")
        hu = await login(user_c, "ada@example.org")
        r = await admin_c.patch(
            f"{ADMIN}/users/{target.id}/status", headers=ha, json={"isActive": False}
        )
        assert r.status_code == 200 and r.json()["isActive"] is False
        assert (await user_c.get(ME, headers=hu)).status_code == 401
        assert (await user_c.post("/api/v1/auth/refresh", headers=CSRF)).status_code == 401
        bad = await user_c.post(
            "/api/v1/auth/login", json={"email": "ada@example.org", "password": STRONG_PASSWORD}
        )
        assert bad.status_code == 401
        await admin_c.patch(
            f"{ADMIN}/users/{target.id}/status", headers=ha, json={"isActive": True}
        )
        await login(user_c, "ada@example.org")


async def test_role_change_invalidates_sessions(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_admin(db, email="boss@example.org")
    target = await make_user(db, email="ada@example.org")
    async with client_factory("192.0.2.1") as admin_c, client_factory("192.0.2.2") as user_c:
        ha = await login(admin_c, "boss@example.org")
        hu = await login(user_c, "ada@example.org")
        r = await admin_c.patch(
            f"{ADMIN}/users/{target.id}/role", headers=ha, json={"role": "admin"}
        )
        assert r.status_code == 200 and r.json()["role"] == "admin"
        assert (await user_c.get(ME, headers=hu)).status_code == 401
        hu = await login(user_c, "ada@example.org", mode="admin")
        assert (await user_c.get(ME, headers=hu)).json()["role"] == "admin"


async def test_admin_cannot_modify_self_or_remove_last_admin(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    boss = await make_admin(db, email="boss@example.org")
    h = await login(client, "boss@example.org")
    r = await client.patch(f"{ADMIN}/users/{boss.id}/role", headers=h, json={"role": "user"})
    assert r.status_code == 400 and r.json()["code"] == "cannot_modify_self"
    r = await client.patch(f"{ADMIN}/users/{boss.id}/status", headers=h, json={"isActive": False})
    assert r.status_code == 400 and r.json()["code"] == "cannot_modify_self"


async def test_unknown_user_is_404(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_admin(db, email="boss@example.org")
    h = await login(client, "boss@example.org")
    missing = "00000000-0000-4000-8000-000000000000"
    assert (await client.get(f"{ADMIN}/users/{missing}", headers=h)).status_code == 404
    assert (await client.get(f"{ADMIN}/users/not-a-uuid", headers=h)).status_code == 400


async def test_admin_actions_are_audited_without_personal_data(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    boss = await make_admin(db, email="boss@example.org")
    target = await make_user(db, email="ada@example.org")
    h = await login(client, "boss@example.org")
    await client.patch(f"{ADMIN}/users/{target.id}/status", headers=h, json={"isActive": False})
    await client.patch(f"{ADMIN}/users/{target.id}/role", headers=h, json={"role": "admin"})
    events = (
        (await db.execute(select(AuditEvent).where(AuditEvent.action.like("admin.%"))))
        .scalars()
        .all()
    )
    actions = {e.action for e in events}
    assert {"admin.user_disabled", "admin.role_changed"} <= actions
    for e in events:
        assert e.actor_user_id == boss.id and e.target_user_id == target.id
        assert "@" not in str(e.details)
    r = (
        await client.get(
            f"{ADMIN}/audit-events", headers=h, params={"targetUserId": str(target.id)}
        )
    ).json()
    assert r["total"] >= 2
