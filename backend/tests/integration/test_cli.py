from __future__ import annotations

import io

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.auth.password_policy import PasswordPolicy
from netribeat.auth.security import verify_password
from netribeat.cli import CliError, create_admin, read_new_password, set_active, set_role
from netribeat.clock import FrozenClock
from netribeat.users.models import Role, UserSource
from tests.conftest import STRONG_PASSWORD
from tests.factories import make_admin, make_user

POLICY = PasswordPolicy(12, 128)


async def test_create_admin_new(db: AsyncSession, clock: FrozenClock) -> None:
    user = await create_admin(
        db, clock, email="ops@example.org", first_name="Op", last_name="S", password=STRONG_PASSWORD
    )
    assert user.role is Role.ADMIN and user.email_verified_at is not None
    assert verify_password(user.password_hash, STRONG_PASSWORD)


async def test_create_admin_on_passwordless_user_sets_password_and_role(
    db: AsyncSession, clock: FrozenClock
) -> None:
    existing = await make_user(
        db, email="ops@example.org", password=None, source=UserSource.UPLOAD, verified=False
    )
    user = await create_admin(
        db, clock, email="ops@example.org", first_name="Op", last_name="S", password=STRONG_PASSWORD
    )
    assert user.id == existing.id and user.role is Role.ADMIN and user.has_password


async def test_create_admin_refuses_existing_login(db: AsyncSession, clock: FrozenClock) -> None:
    await make_user(db, email="ops@example.org")
    with pytest.raises(CliError, match="already has a login"):
        await create_admin(
            db,
            clock,
            email="ops@example.org",
            first_name="O",
            last_name="S",
            password=STRONG_PASSWORD,
        )


def test_password_prompt_rejects_mismatch_and_weak() -> None:
    answers = iter([STRONG_PASSWORD, "different strong phrase"])
    with pytest.raises(CliError, match="don't match"):
        read_new_password(
            POLICY, email="a@x.org", names=(), from_stdin=False, prompt=lambda _: next(answers)
        )
    with pytest.raises(CliError, match="Password rejected"):
        read_new_password(
            POLICY, email="a@x.org", names=(), from_stdin=True, stdin=io.StringIO("password1234\n")
        )
    assert (
        read_new_password(
            POLICY,
            email="a@x.org",
            names=(),
            from_stdin=True,
            stdin=io.StringIO(STRONG_PASSWORD + "\n"),
        )
        == STRONG_PASSWORD
    )


async def test_set_role_bumps_token_version(db: AsyncSession, clock: FrozenClock) -> None:
    await make_admin(db, email="boss@example.org")
    user = await make_user(db, email="ada@example.org")
    before = user.token_version
    user = await set_role(db, clock, email="ada@example.org", role=Role.ADMIN)
    assert user.role is Role.ADMIN and user.token_version == before + 1


async def test_cannot_demote_or_disable_last_admin(db: AsyncSession, clock: FrozenClock) -> None:
    await make_admin(db, email="boss@example.org")
    with pytest.raises(CliError, match="last active admin"):
        await set_role(db, clock, email="boss@example.org", role=Role.USER)
    with pytest.raises(CliError, match="last active admin"):
        await set_active(db, clock, email="boss@example.org", active=False)


async def test_disable_user(db: AsyncSession, clock: FrozenClock) -> None:
    await make_user(db, email="ada@example.org")
    user = await set_active(db, clock, email="ada@example.org", active=False)
    assert user.is_active is False and user.token_version == 1
