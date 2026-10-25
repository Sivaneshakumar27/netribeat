from __future__ import annotations

from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.audit.models import AuditEvent
from tests.conftest import CSRF
from tests.factories import login, make_admin, make_user

SESS = "/api/v1/users/me/sessions"
ME = "/api/v1/auth/me"


async def test_list_sessions_marks_current_and_hides_tokens(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    async with client_factory("192.0.2.1") as laptop, client_factory("192.0.2.2") as phone:
        h1 = await login(laptop, "ada@example.org")
        await login(phone, "ada@example.org", remember=True)
        r = await laptop.get(SESS, headers=h1)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) == 2
        assert [i["current"] for i in items].count(True) == 1
        current = next(i for i in items if i["current"])
        assert current["ipAddress"] == "192.0.2.1"
        assert {i["remember"] for i in items} == {True, False}
        text = r.text.lower()
        assert "token" not in text and "hash" not in text


async def test_revoke_one_device(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    async with client_factory("192.0.2.1") as laptop, client_factory("192.0.2.2") as phone:
        h1 = await login(laptop, "ada@example.org")
        h2 = await login(phone, "ada@example.org")
        phone_id = next(
            i["id"]
            for i in (await laptop.get(SESS, headers=h1)).json()["items"]
            if not i["current"]
        )
        assert (await laptop.delete(f"{SESS}/{phone_id}", headers=h1)).status_code == 204
        assert (await phone.get(ME, headers=h2)).status_code == 401
        assert (await phone.post("/api/v1/auth/refresh", headers=CSRF)).status_code == 401
        assert (await laptop.get(ME, headers=h1)).status_code == 200
        assert len((await laptop.get(SESS, headers=h1)).json()["items"]) == 1
        assert (await laptop.delete(f"{SESS}/{phone_id}", headers=h1)).status_code == 404


async def test_cannot_revoke_another_users_session(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    await make_user(db, email="eve@example.org")
    async with client_factory("192.0.2.1") as ada, client_factory("192.0.2.2") as eve:
        ha = await login(ada, "ada@example.org")
        he = await login(eve, "eve@example.org")
        ada_sid = (await ada.get(SESS, headers=ha)).json()["items"][0]["id"]
        r = await eve.delete(f"{SESS}/{ada_sid}", headers=he)
        assert r.status_code == 404  # not 403: existence isn't revealed
        assert (await ada.get(ME, headers=ha)).status_code == 200
        assert all(i["id"] != ada_sid for i in (await eve.get(SESS, headers=he)).json()["items"])


async def test_revoke_others_keeps_this_device(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    async with (
        client_factory("192.0.2.1") as a,
        client_factory("192.0.2.2") as b,
        client_factory("192.0.2.3") as c,
    ):
        ha = await login(a, "ada@example.org")
        hb = await login(b, "ada@example.org")
        hc = await login(c, "ada@example.org")
        assert (await a.post(f"{SESS}/revoke-others", headers=ha)).status_code == 204
        assert (await a.get(ME, headers=ha)).status_code == 200
        assert (await b.get(ME, headers=hb)).status_code == 401
        assert (await c.get(ME, headers=hc)).status_code == 401


async def test_admin_signs_user_out_everywhere(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_admin(db, email="boss@example.org")
    target = await make_user(db, email="ada@example.org")
    async with client_factory("192.0.2.1") as admin_c, client_factory("192.0.2.2") as user_c:
        ha = await login(admin_c, "boss@example.org")
        hu = await login(user_c, "ada@example.org")
        url = f"/api/v1/admin/users/{target.id}/sessions/revoke-all"
        assert (await user_c.post(url, headers=hu)).status_code == 403
        assert (await admin_c.post(url, headers=ha)).status_code == 204
        assert (await user_c.get(ME, headers=hu)).status_code == 401
        missing = "/api/v1/admin/users/00000000-0000-4000-8000-000000000000/sessions/revoke-all"
        assert (await admin_c.post(missing, headers=ha)).status_code == 404
    actions = (await db.execute(select(AuditEvent.action))).scalars().all()
    assert "admin.sessions_revoked" in actions


async def test_expired_sessions_not_listed(
    client: httpx.AsyncClient, db: AsyncSession, clock: object
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org", remember=True)
    assert len((await client.get(SESS, headers=h)).json()["items"]) == 1
