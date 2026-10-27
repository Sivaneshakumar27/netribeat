"""Sessions: upload, analyse, list, and the max-HR setting that drives zones and load.

A `user` sees and uploads only their own sessions; an `admin` sees all and uploads for anyone.
Analysis runs during the upload request (hex files decode in about a second).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from netribeat.auth import audit
from netribeat.auth.models import HrMaxMethod, User
from netribeat.auth.service import RequestContext
from netribeat.clock import Clock
from netribeat.core.errors import Forbidden, NotFound, ValidationFailed
from netribeat.sessions import engine
from netribeat.sessions.models import Recording
from netribeat.sessions.processing import (
    Inputs,
    ProcessingError,
    analyse,
    athlete_name,
    decode,
)
from netribeat.sessions.processing import reanalyse_advanced as reanalyse_advanced_hrv
from netribeat.sessions.schemas import HrMaxOption, HrMaxSettingsOut

MAX_FILES = 10
MAX_FILE_BYTES = 20 * 1024 * 1024
LABELS = {
    "override": "Upload override",
    "manual": "Manual",
    "peak": "Peak from sessions",
    "age": "Age formula (210 - 0.65 x age)",
}


@dataclass(frozen=True)
class UploadForm:
    type: str
    device: str
    recorded_at: datetime | None
    age: int | None
    hr_max_manual: int | None
    notes: str | None
    user_id: uuid.UUID | None  # admins only
    # Athlete details (optional; never taken from the account profile)
    athlete_name: str | None = None  # empty -> from the file name
    gender: str | None = None
    resting_hr: int | None = None
    height_cm: int | None = None
    weight_kg: float | None = None


def _visible(stmt: Select[tuple[Recording]], user: User) -> Select[tuple[Recording]]:
    return stmt if user.is_admin else stmt.where(Recording.user_id == user.id)


async def get(
    db: AsyncSession, user: User, session_id: uuid.UUID, *, full: bool = False
) -> Recording:
    stmt = _visible(select(Recording).where(Recording.id == session_id), user)
    if full:
        stmt = stmt.options(undefer(Recording.signals), undefer(Recording.file_data))
    rec = (await db.execute(stmt)).scalar_one_or_none()
    if rec is None:
        raise NotFound("Session not found")
    return rec


async def owners(db: AsyncSession, recs: Sequence[Recording]) -> dict[uuid.UUID, User]:
    ids = {r.user_id for r in recs}
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars()
    return {u.id: u for u in rows}


async def list_sessions(
    db: AsyncSession,
    user: User,
    *,
    q: str | None,
    user_id: uuid.UUID | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Recording], int, dict[str, float | int | None]]:
    stmt = _visible(select(Recording), user)
    if user_id:
        stmt = stmt.where(Recording.user_id == user_id)
    if status:
        stmt = stmt.where(Recording.status == status)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.join(User, User.id == Recording.user_id).where(
            or_(
                func.lower(Recording.file_name).like(like),
                func.lower(User.email).like(like),
                func.lower(User.first_name + " " + User.last_name).like(like),
                Recording.notes.ilike(like),
            )
        )
    sub = stmt.subquery()
    total, users, seconds = (
        await db.execute(
            select(
                func.count(), func.count(func.distinct(sub.c.user_id)), func.sum(sub.c.duration_s)
            )
        )
    ).one()
    rows = (
        (
            await db.execute(
                stmt.order_by(Recording.recorded_at.desc(), Recording.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    stats = {"sessions": total, "users": users, "recorded_time_s": float(seconds or 0)}
    return rows, int(total), stats


# ------------------------------------------------------------------ max HR


async def peak_hr(db: AsyncSession, user_id: uuid.UUID) -> float | None:
    value = await db.scalar(
        select(func.max(Recording.max_hr)).where(
            Recording.user_id == user_id, Recording.status == "ready"
        )
    )
    return float(value) if value is not None else None


def _inputs(rec: Recording) -> Inputs:
    """Athlete details from this upload only (one account tests many athletes, so the account
    profile is never used): entered values, the name from the file name, otherwise None."""
    used = "override" if rec.hr_max_manual else "age" if rec.age is not None else None
    return Inputs(
        name=athlete_name(rec.athlete_name, rec.file_name),
        age=rec.age,
        gender=rec.gender,
        resting_hr=rec.resting_hr,
        height_cm=rec.height_cm,
        weight_kg=rec.weight_kg,
        max_hr=float(rec.hr_max_manual) if rec.hr_max_manual else None,
        max_hr_label=LABELS[used] if used else "",
        max_hr_method=used,
    )


async def hr_max_settings(db: AsyncSession, target: User) -> HrMaxSettingsOut:
    peak = await peak_hr(db, target.id)
    age_value = round(engine.theoretical_max_hr(target.age)) if target.age else None
    options = [
        HrMaxOption(
            method="age",
            value=age_value,
            detail=f"210 - 0.65 x {target.age}" if target.age else "Set your age in Profile",
        ),
        HrMaxOption(
            method="peak",
            value=round(peak) if peak else None,
            detail="Highest max HR in your sessions" if peak else "No analysed sessions yet",
        ),
        HrMaxOption(
            method="manual",
            value=target.hr_max_manual,
            detail="Entered by you" if target.hr_max_manual else "Not set",
        ),
    ]
    method = target.hr_max_method.value if target.hr_max_method else None
    effective = next((o for o in options if o.method == (method or "age")), None)
    ready = await db.scalar(
        select(func.count()).where(Recording.user_id == target.id, Recording.status == "ready")
    )
    return HrMaxSettingsOut(
        method=method,
        manual_value=target.hr_max_manual,
        options=options,
        effective=effective if effective and effective.value else None,
        sessions_ready=int(ready or 0),
    )


async def set_hr_max(
    db: AsyncSession,
    clock: Clock,
    *,
    actor: User,
    target: User,
    method: str,
    manual_value: int | None,
    ctx: RequestContext,
) -> HrMaxSettingsOut:
    if method == "manual" and manual_value is None:
        raise ValidationFailed(fields={"manualValue": "Enter a max HR between 100 and 230 bpm"})
    if method == "peak" and await peak_hr(db, target.id) is None:
        raise ValidationFailed(fields={"method": "No analysed sessions to take a peak from"})
    target.hr_max_method = HrMaxMethod(method)
    target.hr_max_manual = manual_value if method == "manual" else target.hr_max_manual
    audit.record(
        db,
        action="user.hr_max_changed",
        now=clock.now(),
        actor_id=actor.id,
        target_id=target.id,
        ip=ctx.ip,
        details={"method": method},
    )
    await db.commit()
    count = await reanalyse_user(db, clock, target)
    out = await hr_max_settings(db, target)
    out.recomputed_sessions = count
    return out


# ------------------------------------------------------------------ upload and analysis


async def _apply(
    db: AsyncSession, clock: Clock, rec: Recording, owner: User, df: pd.DataFrame
) -> None:
    rec.attempts += 1
    rec.processed_at = clock.now()
    try:
        result = await asyncio.to_thread(analyse, df, _inputs(rec))
    except ValueError as exc:  # the engine's own "can't analyse" errors
        rec.status, rec.error = "failed", str(exc)[:500]
        return
    m = result.metrics
    rec.status, rec.error = "ready", None
    if rec.recorded_at_source == "file":  # else keep the entered / upload time (stable re-runs)
        rec.recorded_at = result.recorded_at
    rec.duration_s = result.duration_s
    rec.avg_hr, rec.max_hr, rec.min_hr = m["hr"]["avg"], m["hr"]["max"], m["hr"]["min"]
    rec.training_load, rec.movement_load = m["trainingLoad"], m["movementLoad"]
    rec.metrics, rec.signals = m, result.signals


def _fallback_start_ms(rec: Recording) -> int:
    return int(rec.recorded_at.timestamp() * 1000)


async def reanalyse(db: AsyncSession, clock: Clock, rec: Recording, owner: User) -> None:
    """Analyse a stored session again from its original file."""
    try:
        sessions = await asyncio.to_thread(
            decode, rec.file_data, rec.file_name, _fallback_start_ms(rec)
        )
        if rec.part >= len(sessions):
            raise ProcessingError("The session is no longer found in the file")
        await _apply(db, clock, rec, owner, sessions[rec.part])
    except ProcessingError as exc:
        rec.attempts += 1
        rec.status, rec.error = "failed", str(exc)
    await db.commit()


async def reanalyse_user(db: AsyncSession, clock: Clock, owner: User) -> int:
    recs = (
        (
            await db.execute(
                select(Recording)
                .where(Recording.user_id == owner.id)
                .options(undefer(Recording.file_data))
                .order_by(Recording.recorded_at)
            )
        )
        .scalars()
        .all()
    )
    for rec in recs:
        await reanalyse(db, clock, rec, owner)
    return len(recs)


async def upload(
    db: AsyncSession,
    clock: Clock,
    *,
    actor: User,
    files: list[tuple[str, bytes]],
    form: UploadForm,
    ctx: RequestContext,
) -> list[Recording]:
    if not files:
        raise ValidationFailed(fields={"files": "Choose at least one hex file"})
    if len(files) > MAX_FILES:
        raise ValidationFailed(fields={"files": f"Upload at most {MAX_FILES} files at once"})
    owner = actor
    if form.user_id and form.user_id != actor.id:
        if not actor.is_admin:
            raise Forbidden("You can only upload your own sessions")
        found = await db.get(User, form.user_id)
        if found is None:
            raise ValidationFailed(fields={"userId": "User not found"})
        owner = found

    now = clock.now()
    fallback = form.recorded_at or now
    decoded: list[tuple[str, bytes, list[pd.DataFrame]]] = []
    problems: dict[str, str] = {}
    for i, (name, data) in enumerate(files):
        if len(data) > MAX_FILE_BYTES:
            problems[f"files.{i}"] = f"{name}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"
            continue
        try:
            sessions = await asyncio.to_thread(decode, data, name, int(fallback.timestamp() * 1000))
        except ProcessingError as exc:
            problems[f"files.{i}"] = f"{name}: {exc}"
            continue
        decoded.append((name, data, sessions))
    if problems:
        raise ValidationFailed("Some files can't be analysed", fields=problems)

    created: list[Recording] = []
    for name, data, sessions in decoded:
        from_file = engine.start_time_from_filename(name) is not None
        for part, df in enumerate(sessions):
            rec = Recording(
                user_id=owner.id,
                uploaded_by_id=actor.id,
                type=form.type,
                device=form.device,
                notes=form.notes,
                age=form.age,
                age_source="entered" if form.age is not None else "none",
                hr_max_manual=form.hr_max_manual,
                athlete_name=(form.athlete_name or "").strip() or None,
                gender=form.gender,
                resting_hr=form.resting_hr,
                height_cm=form.height_cm,
                weight_kg=form.weight_kg,
                recorded_at=fallback,
                recorded_at_source="file"
                if from_file
                else "entered"
                if form.recorded_at
                else "upload",
                file_name=name[:255],
                file_size=len(data),
                file_data=data,
                part=part,
                status="processing",
                attempts=0,
            )
            db.add(rec)
            await _apply(db, clock, rec, owner, df)
            created.append(rec)
    await db.flush()
    audit.record(
        db,
        action="session.uploaded",
        now=now,
        actor_id=actor.id,
        target_id=owner.id,
        ip=ctx.ip,
        details={"sessions": len(created), "files": len(decoded)},
    )
    await db.commit()
    return created


async def delete(
    db: AsyncSession, clock: Clock, user: User, rec: Recording, ctx: RequestContext
) -> None:
    if not user.is_admin and rec.user_id != user.id:
        raise Forbidden()
    audit.record(
        db,
        action="session.deleted",
        now=clock.now(),
        actor_id=user.id,
        target_id=rec.user_id,
        ip=ctx.ip,
        details={"session_id": str(rec.id)},
    )
    await db.delete(rec)
    await db.commit()


async def reanalyse_advanced(
    db: AsyncSession,
    clock: Clock,
    user: User,
    rec: Recording,
    options: dict[str, object],
    ctx: RequestContext,
) -> Recording:
    """Advanced HRV again with new options; stored, so the screens and the PDF agree."""
    try:
        metrics, series = await asyncio.to_thread(
            reanalyse_advanced_hrv, rec.signals or {}, options
        )
    except (TypeError, ValueError) as exc:
        raise ValidationFailed(str(exc), fields={"options": str(exc)}) from None
    rec.metrics = {**(rec.metrics or {}), "advanced": metrics}
    rec.signals = {**(rec.signals or {}), "advanced": series}
    audit.record(
        db,
        action="session.reanalysed",
        now=clock.now(),
        actor_id=user.id,
        target_id=rec.user_id,
        ip=ctx.ip,
        details={"session_id": str(rec.id)},
    )
    await db.commit()
    return rec
