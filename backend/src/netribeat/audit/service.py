"""Record and read security audit events. Callers pass ids only."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.audit.models import AuditEvent

FORBIDDEN_DETAIL_KEYS = frozenset({"email", "password", "otp", "code", "token", "reset_token"})


def record(
    db: AsyncSession,
    *,
    action: str,
    now: datetime,
    actor_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit row to the caller's transaction (committed with the change it describes)."""
    clean = dict(details or {})
    leaked = FORBIDDEN_DETAIL_KEYS.intersection(k.lower() for k in clean)
    if leaked:
        raise ValueError(f"audit details must not contain {sorted(leaked)}")
    if actor_id is not None:
        clean.setdefault("actor_id", str(actor_id))
    if target_id is not None:
        clean.setdefault("target_id", str(target_id))
    db.add(
        AuditEvent(
            created_at=now,
            action=action,
            actor_user_id=actor_id,
            target_user_id=target_id,
            ip_address=ip,
            details=clean,
        )
    )


async def list_events(
    db: AsyncSession,
    *,
    action: str | None,
    target_id: uuid.UUID | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[AuditEvent], int]:
    stmt = select(AuditEvent)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if target_id:
        stmt = stmt.where(AuditEvent.target_user_id == target_id)
    total = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (
        (
            await db.execute(
                stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return rows, total
