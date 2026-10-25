from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.auth.models import AuthChallenge
from netribeat.clock import FrozenClock
from netribeat.email.service import MemoryEmailSender
from netribeat.users.models import Role, User
from tests.conftest import STRONG_PASSWORD, code_from, last_mail, table_count
from tests.factories import make_user

REG = "/api/v1/auth/register"
VERIFY = "/api/v1/auth/verify-email"
RESEND = "/api/v1/auth/resend-verification"


def body(email: str = "new.person@example.org", **over: object) -> dict[str, object]:
    data: dict[str, object] = {
        "firstName": "New",
        "lastName": "Person",
        "email": email,
        "password": STRONG_PASSWORD,
        "confirmPassword": STRONG_PASSWORD,
    }
    data.update(over)
    return data


async def test_register_verify_login_happy_path(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    resp = await client.post(REG, json=body(email="  New.Person@Example.ORG "))
    assert resp.status_code == 202
    assert resp.json()["status"] == "verification_pending"
    # Not an account yet: login refused, no users row.
    assert await table_count(db, "users") == 0
    code = code_from(last_mail(mail, "new.person@example.org", "verify_email"))

    resp = await client.post(VERIFY, json={"email": "new.person@example.org", "code": code})
    assert resp.status_code == 200, resp.text
    user = resp.json()
    assert user["role"] == "user" and user["emailVerified"] is True
    assert user["email"] == "new.person@example.org"  # normalised
    last_mail(mail, "new.person@example.org", "account_activated")
    assert await table_count(db, "pending_registrations") == 0

    resp = await client.post(
        "/api/v1/auth/login", json={"email": "new.person@example.org", "password": STRONG_PASSWORD}
    )
    assert resp.status_code == 200


async def test_register_rejects_admin_role(client: httpx.AsyncClient, db: AsyncSession) -> None:
    resp = await client.post(REG, json=body(role="admin"))
    assert resp.status_code == 400
    assert resp.json()["fields"]["role"] == "Public registration can only create a user account"
    assert await table_count(db, "pending_registrations") == 0


async def test_register_with_role_user_is_accepted(client: httpx.AsyncClient) -> None:
    assert (await client.post(REG, json=body(role="user"))).status_code == 202


async def test_verified_account_is_never_admin_even_if_db_pending_tampered(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await client.post(REG, json=body())
    code = code_from(last_mail(mail, "new.person@example.org", "verify_email"))
    await client.post(VERIFY, json={"email": "new.person@example.org", "code": code})
    user = (await db.execute(select(User))).scalar_one()
    assert user.role is Role.USER


async def test_register_unknown_fields_rejected(client: httpx.AsyncClient) -> None:
    resp = await client.post(REG, json=body(isAdmin=True))
    assert resp.status_code == 400
    assert "isAdmin" in resp.json()["fields"]


async def test_register_validation_messages(client: httpx.AsyncClient) -> None:
    resp = await client.post(REG, json={"email": "not-an-email", "password": "x"})
    assert resp.status_code == 400
    f = resp.json()["fields"]
    assert f["email"] == "Enter a valid email address, like name@institute.org"
    assert f["firstName"] == "Enter your first name"
    assert f["confirmPassword"] == "Confirm your password"


async def test_register_password_mismatch(client: httpx.AsyncClient) -> None:
    resp = await client.post(REG, json=body(confirmPassword="something else entirely"))
    assert resp.status_code == 400
    assert resp.json()["fields"]["confirmPassword"] == "Passwords don't match"


async def test_register_weak_password(client: httpx.AsyncClient) -> None:
    resp = await client.post(REG, json=body(password="short", confirmPassword="short"))
    assert resp.status_code == 400
    assert resp.json()["fields"]["password"] == "Use at least 12 characters"


async def test_register_existing_email_is_indistinguishable(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await make_user(db, email="taken@example.org")
    fresh = await client.post(REG, json=body(email="fresh@example.org"))
    taken = await client.post(REG, json=body(email="taken@example.org"))
    assert taken.status_code == fresh.status_code == 202
    assert taken.json() == fresh.json()
    # The real owner gets a notice instead of a code; no pending row is created.
    notice = last_mail(mail, "taken@example.org", "account_exists")
    assert "Forgot password" in notice.text
    assert not [
        m for m in mail.sent if m.to == "taken@example.org" and m.template == "verify_email"
    ]
    assert await table_count(db, "pending_registrations") == 1  # only fresh@


async def test_verify_wrong_code_then_lockout(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await client.post(REG, json=body())
    code = code_from(last_mail(mail, "new.person@example.org", "verify_email"))
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        r = await client.post(VERIFY, json={"email": "new.person@example.org", "code": wrong})
        assert r.status_code == 400 and r.json()["code"] == "invalid_code"
    # After 5 failures the challenge is closed: even the right code fails now.
    r = await client.post(VERIFY, json={"email": "new.person@example.org", "code": code})
    assert r.status_code == 400
    ch = (await db.execute(select(AuthChallenge))).scalar_one()
    assert ch.close_reason == "exhausted"
    assert await table_count(db, "users") == 0


async def test_verify_expired_code(
    client: httpx.AsyncClient, mail: MemoryEmailSender, clock: FrozenClock
) -> None:
    await client.post(REG, json=body())
    code = code_from(last_mail(mail, "new.person@example.org", "verify_email"))
    clock.advance(minutes=10)
    r = await client.post(VERIFY, json={"email": "new.person@example.org", "code": code})
    assert r.status_code == 400 and r.json()["code"] == "invalid_code"


async def test_code_is_single_use(client: httpx.AsyncClient, mail: MemoryEmailSender) -> None:
    await client.post(REG, json=body())
    code = code_from(last_mail(mail, "new.person@example.org", "verify_email"))
    first = await client.post(VERIFY, json={"email": "new.person@example.org", "code": code})
    second = await client.post(VERIFY, json={"email": "new.person@example.org", "code": code})
    assert first.status_code == 200 and second.status_code == 400


async def test_code_for_other_email_does_not_work(
    client: httpx.AsyncClient, mail: MemoryEmailSender
) -> None:
    await client.post(REG, json=body(email="a@example.org"))
    await client.post(REG, json=body(email="b@example.org"))
    code_a = code_from(last_mail(mail, "a@example.org", "verify_email"))
    r = await client.post(VERIFY, json={"email": "b@example.org", "code": code_a})
    if r.status_code == 200:  # astronomically unlikely identical codes
        return
    assert r.status_code == 400


async def test_otp_stored_only_as_hash(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await client.post(REG, json=body())
    code = code_from(last_mail(mail, "new.person@example.org", "verify_email"))
    ch = (await db.execute(select(AuthChallenge))).scalar_one()
    assert code not in ch.code_hash and len(ch.code_hash) == 64


async def test_resend_respects_cooldown_and_supersedes_old_code(
    client: httpx.AsyncClient, mail: MemoryEmailSender, clock: FrozenClock
) -> None:
    await client.post(REG, json=body())
    first = code_from(last_mail(mail, "new.person@example.org", "verify_email"))

    r = await client.post(RESEND, json={"email": "new.person@example.org"})
    assert r.status_code == 202
    assert len([m for m in mail.sent if m.template == "verify_email"]) == 1  # cooldown

    clock.advance(seconds=61)
    await client.post(RESEND, json={"email": "new.person@example.org"})
    second = code_from(last_mail(mail, "new.person@example.org", "verify_email"))
    assert len([m for m in mail.sent if m.template == "verify_email"]) == 2

    if first != second:
        old = await client.post(VERIFY, json={"email": "new.person@example.org", "code": first})
        assert old.status_code == 400
    ok = await client.post(VERIFY, json={"email": "new.person@example.org", "code": second})
    assert ok.status_code == 200


async def test_resend_hourly_cap_is_silent(
    client: httpx.AsyncClient, mail: MemoryEmailSender, clock: FrozenClock
) -> None:
    await client.post(REG, json=body())
    for _ in range(5):
        clock.advance(seconds=61)
        r = await client.post(RESEND, json={"email": "new.person@example.org"})
        assert r.status_code == 202
    assert len([m for m in mail.sent if m.template == "verify_email"]) == 3  # cap = 3/hour


async def test_resend_for_unknown_email_is_generic(
    client: httpx.AsyncClient, mail: MemoryEmailSender
) -> None:
    r = await client.post(RESEND, json={"email": "nobody@example.org"})
    assert r.status_code == 202
    assert mail.sent == []


async def test_register_ip_rate_limit(client: httpx.AsyncClient) -> None:
    for i in range(10):
        assert (await client.post(REG, json=body(email=f"p{i}@example.org"))).status_code == 202
    r = await client.post(REG, json=body(email="p11@example.org"))
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"


async def test_reregistering_pending_email_replaces_details(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession, clock: FrozenClock
) -> None:
    await client.post(REG, json=body(firstName="First"))
    clock.advance(seconds=61)
    await client.post(REG, json=body(firstName="Second"))
    assert await table_count(db, "pending_registrations") == 1
    code = code_from(last_mail(mail, "new.person@example.org", "verify_email"))
    r = await client.post(VERIFY, json={"email": "new.person@example.org", "code": code})
    assert r.json()["firstName"] == "Second"


async def test_verify_when_account_created_meanwhile_conflicts(
    client: httpx.AsyncClient, mail: MemoryEmailSender, db: AsyncSession
) -> None:
    await client.post(REG, json=body())
    code = code_from(last_mail(mail, "new.person@example.org", "verify_email"))
    await make_user(db, email="new.person@example.org")  # e.g. an admin created it
    r = await client.post(VERIFY, json={"email": "new.person@example.org", "code": code})
    assert r.status_code == 409 and r.json()["code"] == "account_exists"
