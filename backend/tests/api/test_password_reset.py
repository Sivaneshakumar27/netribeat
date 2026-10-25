from __future__ import annotations

from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.auth.models import AuthChallenge
from netribeat.clock import FrozenClock
from netribeat.email.service import MemoryEmailSender
from netribeat.users.models import UserSource
from tests.conftest import CSRF, OTHER_STRONG_PASSWORD, STRONG_PASSWORD, code_from, last_mail
from tests.factories import login, make_user

FORGOT = "/api/v1/auth/forgot-password"
VERIFY = "/api/v1/auth/verify-reset-otp"
RESET = "/api/v1/auth/reset-password"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


async def _reset_token(client: httpx.AsyncClient, mail: MemoryEmailSender, email: str) -> str:
    assert (await client.post(FORGOT, json={"email": email})).status_code == 202
    code = code_from(last_mail(mail, email, "password_reset_code"))
    r = await client.post(VERIFY, json={"email": email, "code": code})
    assert r.status_code == 200, r.text
    token: str = r.json()["resetToken"]
    return token


def _reset_body(token: str, pw: str = OTHER_STRONG_PASSWORD) -> dict[str, str]:
    return {"resetToken": token, "password": pw, "confirmPassword": pw}


async def test_forgot_password_is_identical_for_known_and_unknown(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    known = await client.post(FORGOT, json={"email": "ada@example.org"})
    unknown = await client.post(FORGOT, json={"email": "ghost@example.org"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [m.to for m in mail.sent] == ["ada@example.org"]


async def test_reset_email_contains_no_password(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    await client.post(FORGOT, json={"email": "ada@example.org"})
    assert STRONG_PASSWORD not in mail.sent[0].text


async def test_full_reset_flow_signs_out_everywhere(
    client_factory: Callable[[str], httpx.AsyncClient],
    mail: MemoryEmailSender,
    db: AsyncSession,
) -> None:
    await make_user(db, email="ada@example.org")
    async with client_factory("192.0.2.1") as other_device, client_factory("192.0.2.2") as c:
        old_headers = await login(other_device, "ada@example.org")
        token = await _reset_token(c, mail, "ada@example.org")
        r = await c.post(RESET, json=_reset_body(token))
        assert r.status_code == 204

        assert (await other_device.get(ME, headers=old_headers)).status_code == 401
        assert (await other_device.post("/api/v1/auth/refresh", headers=CSRF)).status_code == 401
        old = await c.post(LOGIN, json={"email": "ada@example.org", "password": STRONG_PASSWORD})
        assert old.status_code == 401
        await login(c, "ada@example.org", OTHER_STRONG_PASSWORD)
        done = last_mail(mail, "ada@example.org", "password_reset_done")
        assert OTHER_STRONG_PASSWORD not in done.text


async def test_reset_token_is_single_use(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    token = await _reset_token(client, mail, "ada@example.org")
    assert (await client.post(RESET, json=_reset_body(token))).status_code == 204
    r = await client.post(RESET, json=_reset_body(token, "another strong passphrase"))
    assert r.status_code == 400 and r.json()["code"] == "invalid_reset_token"


async def test_reset_token_expires(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession, clock: FrozenClock
) -> None:
    await make_user(db, email="ada@example.org")
    token = await _reset_token(client, mail, "ada@example.org")
    clock.advance(minutes=10)
    r = await client.post(RESET, json=_reset_body(token))
    assert r.status_code == 400 and r.json()["code"] == "invalid_reset_token"


async def test_otp_cannot_be_verified_twice(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    await client.post(FORGOT, json={"email": "ada@example.org"})
    code = code_from(last_mail(mail, "ada@example.org", "password_reset_code"))
    assert (
        await client.post(VERIFY, json={"email": "ada@example.org", "code": code})
    ).status_code == 200
    again = await client.post(VERIFY, json={"email": "ada@example.org", "code": code})
    assert again.status_code == 400


async def test_reset_otp_attempt_limit(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    await client.post(FORGOT, json={"email": "ada@example.org"})
    code = code_from(last_mail(mail, "ada@example.org", "password_reset_code"))
    wrong = "999999" if code != "999999" else "888888"
    for _ in range(5):
        await client.post(VERIFY, json={"email": "ada@example.org", "code": wrong})
    r = await client.post(VERIFY, json={"email": "ada@example.org", "code": code})
    assert r.status_code == 400


async def test_reset_rejects_weak_and_mismatched_password(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    token = await _reset_token(client, mail, "ada@example.org")
    weak = await client.post(RESET, json=_reset_body(token, "password1234"))
    assert weak.status_code == 400 and "password" in weak.json()["fields"]
    mismatch = await client.post(
        RESET,
        json={
            "resetToken": token,
            "password": OTHER_STRONG_PASSWORD,
            "confirmPassword": "different strong phrase",
        },
    )
    assert mismatch.json()["fields"]["confirmPassword"] == "Passwords don't match"
    # Validation failures don't burn the token.
    assert (await client.post(RESET, json=_reset_body(token))).status_code == 204


async def test_passwordless_imported_user_gets_a_login_via_reset(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await make_user(
        db, email="imported@example.org", password=None, verified=False, source=UserSource.IMPORT
    )
    token = await _reset_token(client, mail, "imported@example.org")
    assert (await client.post(RESET, json=_reset_body(token))).status_code == 204
    headers = await login(client, "imported@example.org", OTHER_STRONG_PASSWORD)
    me = (await client.get(ME, headers=headers)).json()
    assert me["emailVerified"] is True and me["hasPassword"] is True and me["role"] == "user"


async def test_disabled_user_gets_no_reset_email(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org", active=False)
    assert (await client.post(FORGOT, json={"email": "ada@example.org"})).status_code == 202
    assert mail.sent == []


async def test_per_address_cap_is_silent(
    client_factory: Callable[[str], httpx.AsyncClient],
    mail: MemoryEmailSender,
    db: AsyncSession,
    clock: FrozenClock,
) -> None:
    await make_user(db, email="ada@example.org")
    for i in range(5):
        async with client_factory(f"198.51.100.{i}") as c:
            assert (await c.post(FORGOT, json={"email": "ada@example.org"})).status_code == 202
        clock.advance(seconds=61)
    assert len(mail.sent) == 3


async def test_per_ip_limit_returns_429(client: httpx.AsyncClient) -> None:
    for i in range(10):
        assert (await client.post(FORGOT, json={"email": f"n{i}@example.org"})).status_code == 202
    r = await client.post(FORGOT, json={"email": "n11@example.org"})
    assert r.status_code == 429


async def test_new_request_supersedes_previous_code(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession, clock: FrozenClock
) -> None:
    await make_user(db, email="ada@example.org")
    await client.post(FORGOT, json={"email": "ada@example.org"})
    clock.advance(seconds=61)
    await client.post(FORGOT, json={"email": "ada@example.org"})
    rows = (
        (await db.execute(select(AuthChallenge).order_by(AuthChallenge.created_at))).scalars().all()
    )
    assert [r.close_reason for r in rows] == ["superseded", None]


async def test_reset_token_stored_hashed(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    token = await _reset_token(client, mail, "ada@example.org")
    ch = (await db.execute(select(AuthChallenge))).scalar_one()
    assert ch.reset_token_hash and token not in ch.reset_token_hash
