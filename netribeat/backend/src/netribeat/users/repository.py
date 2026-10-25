"""Database access for users. No business rules here (those live in services)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.users.models import Role, User


class UserSort(StrEnum):
    CREATED_DESC = "-createdAt"
    CREATED_ASC = "createdAt"
    EMAIL_ASC = "email"
    EMAIL_DESC = "-email"
    NAME_ASC = "name"
    LAST_LOGIN_DESC = "-lastLoginAt"


_ORDER: dict[UserSort, tuple[Any, ...]] = {
    UserSort.CREATED_DESC: (User.created_at.desc(), User.id),
    UserSort.CREATED_ASC: (User.created_at.asc(), User.id),
    UserSort.EMAIL_ASC: (User.email.asc().nulls_last(), User.id),
    UserSort.EMAIL_DESC: (User.email.desc().nulls_last(), User.id),
    UserSort.NAME_ASC: (User.last_name.asc().nulls_last(), User.first_name.asc(), User.id),
    UserSort.LAST_LOGIN_DESC: (User.last_login_at.desc().nulls_last(), User.id),
}


@dataclass(frozen=True)
class UserFilter:
    q: str | None = None
    role: Role | None = None
    is_active: bool | None = None


async def get_by_id(
    db: AsyncSession, user_id: uuid.UUID, *, for_update: bool = False
) -> User | None:
    stmt = select(User).where(User.id == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_by_email(db: AsyncSession, email: str, *, for_update: bool = False) -> User | None:
    stmt = select(User).where(User.email == email)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered(stmt: Select[tuple[User]], flt: UserFilter) -> Select[tuple[User]]:
    if flt.q:
        pattern = f"%{_escape_like(flt.q.strip().lower())}%"
        stmt = stmt.where(
            or_(
                User.email.ilike(pattern, escape="\\"),
                func.lower(User.first_name).like(pattern, escape="\\"),
                func.lower(User.last_name).like(pattern, escape="\\"),
            )
        )
    if flt.role is not None:
        stmt = stmt.where(User.role == flt.role)
    if flt.is_active is not None:
        stmt = stmt.where(User.is_active == flt.is_active)
    return stmt


async def list_users(
    db: AsyncSession, flt: UserFilter, *, sort: UserSort, limit: int, offset: int
) -> tuple[Sequence[User], int]:
    base = _filtered(select(User), flt)
    total_stmt = select(func.count()).select_from(base.order_by(None).subquery())
    total = int((await db.execute(total_stmt)).scalar_one())
    rows = (
        (await db.execute(base.order_by(*_ORDER[sort]).limit(limit).offset(offset))).scalars().all()
    )
    return rows, total


async def count_active_admins(db: AsyncSession) -> int:
    stmt = select(func.count()).where(User.role == Role.ADMIN, User.is_active.is_(True))
    return int((await db.execute(stmt)).scalar_one())


async def bump_token_version(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(User).where(User.id == user_id).values(token_version=User.token_version + 1)
    )


def add(db: AsyncSession, user: User) -> User:
    db.add(user)
    return user
