"""Database access for pending registrations, challenges and refresh sessions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.auth.models import AuthChallenge, AuthSession, ChallengePurpose, PendingRegistration

# ---------------------------------------------------------------- pending registrations


async def upsert_pending(
    db: AsyncSession,
    *,
    email: str,
    first_name: str,
    last_name: str,
    password_hash: str,
    now: datetime,
    expires_at: datetime,
) -> uuid.UUID:
    """Insert or replace the pending sign-up for this email atomically (ON CONFLICT), so
    concurrent registrations for one email leave exactly one row."""
    stmt = (
        insert(PendingRegistration)
        .values(
            id=uuid.uuid4(),
            email=email,
            first_name=first_name,
            last_name=last_name,
            password_hash=password_hash,
            created_at=now,
            expires_at=expires_at,
        )
        .on_conflict_do_update(
            index_elements=[PendingRegistration.email],
            set_={
                "first_name": first_name,
                "last_name": last_name,
                "password_hash": password_hash,
                "created_at": now,
                "expires_at": expires_at,
            },
        )
        .returning(PendingRegistration.id)
    )
    return (await db.execute(stmt)).scalar_one()


async def get_pending(
    db: AsyncSession, pending_id: uuid.UUID, *, for_update: bool = False
) -> PendingRegistration | None:
    stmt = select(PendingRegistration).where(PendingRegistration.id == pending_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_pending_by_email(db: AsyncSession, email: str) -> PendingRegistration | None:
    stmt = select(PendingRegistration).where(PendingRegistration.email == email)
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_pending(db: AsyncSession, pending_id: uuid.UUID) -> None:
    await db.execute(delete(PendingRegistration).where(PendingRegistration.id == pending_id))


async def delete_expired_pending(db: AsyncSession, now: datetime) -> int:
    result = await db.execute(
        delete(PendingRegistration).where(PendingRegistration.expires_at < now)
    )
    return int(getattr(result, "rowcount", 0) or 0)


# ---------------------------------------------------------------- challenges


async def lock_challenge_slot(db: AsyncSession, *, purpose: ChallengePurpose, email: str) -> None:
    """Serialise challenge issuance per (purpose, email) for the rest of the transaction,
    so concurrent requests can't race on the one-open-challenge unique index."""
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"{purpose.value}:{email}"))))


async def close_open_challenges(
    db: AsyncSession, *, purpose: ChallengePurpose, email: str, now: datetime, reason: str
) -> None:
    await db.execute(
        update(AuthChallenge)
        .where(
            AuthChallenge.purpose == purpose,
            AuthChallenge.email == email,
            AuthChallenge.closed_at.is_(None),
        )
        .values(closed_at=now, close_reason=reason)
    )


async def get_open_challenge(
    db: AsyncSession, *, purpose: ChallengePurpose, email: str, for_update: bool = False
) -> AuthChallenge | None:
    stmt = select(AuthChallenge).where(
        AuthChallenge.purpose == purpose,
        AuthChallenge.email == email,
        AuthChallenge.closed_at.is_(None),
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_challenge_by_reset_hash(
    db: AsyncSession, reset_token_hash: str
) -> AuthChallenge | None:
    stmt = (
        select(AuthChallenge)
        .where(
            AuthChallenge.reset_token_hash == reset_token_hash,
            AuthChallenge.closed_at.is_(None),
        )
        .with_for_update()
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def close_expired_challenges(db: AsyncSession, now: datetime) -> int:
    result = await db.execute(
        update(AuthChallenge)
        .where(AuthChallenge.closed_at.is_(None), AuthChallenge.expires_at < now)
        .values(closed_at=now, close_reason="expired")
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def delete_closed_challenges_before(db: AsyncSession, before: datetime) -> int:
    result = await db.execute(
        delete(AuthChallenge).where(
            AuthChallenge.closed_at.is_not(None), AuthChallenge.closed_at < before
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


# ---------------------------------------------------------------- refresh sessions


async def get_session(db: AsyncSession, session_id: uuid.UUID) -> AuthSession | None:
    return await db.get(AuthSession, session_id)


async def get_session_by_refresh_hash(db: AsyncSession, token_hash: str) -> AuthSession | None:
    stmt = select(AuthSession).where(AuthSession.refresh_token_hash == token_hash).with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_session_by_previous_hash(db: AsyncSession, token_hash: str) -> AuthSession | None:
    stmt = (
        select(AuthSession)
        .where(AuthSession.previous_refresh_token_hash == token_hash)
        .with_for_update()
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_active_sessions(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime
) -> list[AuthSession]:
    stmt = (
        select(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .order_by(AuthSession.last_used_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def revoke_all_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime,
    reason: str,
    except_session: uuid.UUID | None = None,
) -> None:
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revoke_reason=reason)
    )
    if except_session is not None:
        stmt = stmt.where(AuthSession.id != except_session)
    await db.execute(stmt)


async def delete_dead_sessions(db: AsyncSession, before: datetime) -> int:
    result = await db.execute(delete(AuthSession).where(AuthSession.expires_at < before))
    return int(getattr(result, "rowcount", 0) or 0)
