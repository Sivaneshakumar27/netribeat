"""Factories for users and signed-in clients. Synthetic data only."""

from __future__ import annotations

import itertools
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.auth.security import hash_password
from netribeat.users.models import Role, User, UserSource
from tests.conftest import START, STRONG_PASSWORD

_seq = itertools.count(1)
# Hashing is slow by design; reuse one hash for the common password.
_STRONG_HASH = hash_password(STRONG_PASSWORD)


async def make_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    password: str | None = STRONG_PASSWORD,
    role: Role = Role.USER,
    verified: bool = True,
    active: bool = True,
    source: UserSource = UserSource.REGISTRATION,
    **extra: Any,
) -> User:
    n = next(_seq)
    if password is None:
        pw_hash = None
    elif password == STRONG_PASSWORD:
        pw_hash = _STRONG_HASH
    else:
        pw_hash = hash_password(password)
    user = User(
        email=email if email is not None else f"person{n}@example.org",
        first_name=extra.pop("first_name", "Test"),
        last_name=extra.pop("last_name", f"Person{n}"),
        role=role,
        password_hash=pw_hash,
        email_verified_at=START if verified else None,
        is_active=active,
        token_version=0,
        source=source,
        **extra,
    )
    db.add(user)
    await db.commit()
    return user


async def make_admin(db: AsyncSession, **kwargs: Any) -> User:
    return await make_user(db, role=Role.ADMIN, **kwargs)


async def login(
    client: httpx.AsyncClient,
    email: str,
    password: str = STRONG_PASSWORD,
    *,
    mode: str = "user",
    remember: bool = False,
) -> dict[str, str]:
    """Sign in and return Authorization headers."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "mode": mode, "remember": remember},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}
