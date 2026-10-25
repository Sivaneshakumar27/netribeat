"""Session business rules: upload, ownership-checked reads, delete, retry, HRmax.

Ownership: a `user` reaches only sessions whose user_id is their own; anything else
is a 404 (existence isn't revealed). An `admin` reaches every session. The owner of a
new session is always the authenticated actor, unless an admin explicitly uploads for
another user.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.audit import service as audit
from netribeat.auth.service import RequestContext
from netribeat.clock import Clock
from netribeat.config import Settings
from netribeat.core.storage import Storage, new_key
from netribeat.errors import (
    AppError,
    Conflict,
    Forbidden,
    NotFound,
    PayloadTooLarge,
    ValidationFailed,
)
from netribeat.parsers.base import ParserError
from netribeat.parsers.registry import sniff
from netribeat.sessions.jobs import JobQueue
from netribeat.sessions.models import (
    AnalysisResult,
    Device,
    Session,
    SessionFile,
    SessionStatus,
    SessionType,
    ValueSource,
)
from netribeat.sessions.processing import recompute_user_zones, user_peak_hr
from netribeat.users.models import HrMaxMethod, Role, User

log = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = (".json", ".csv", ".txt")


class NotReady(AppError):
    status_code = 409
    code = "not_ready"
    default_message = "The analysis for this session isn't ready"


@dataclass(frozen=True)
class UploadedFile:
    name: str
    data: bytes


@dataclass(frozen=True)
class UploadForm:
    type: SessionType
    device: Device
    recorded_at: datetime | None
    age: int | None
    hr_max_manual: int | None
    notes: str | None
    user_id: uuid.UUID | None  # admins only


@dataclass(frozen=True)
class ListFilter:
    q: str | None = None
    user_id: uuid.UUID | None = None
    status: SessionStatus | None = None


def _safe_name(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1].strip() or "recording"
    return "".join(ch for ch in base if ch.isprintable())[:255]


class SessionService:
    def __init__(
        self,
        *,
        db: AsyncSession,
        storage: Storage,
        queue: JobQueue,
        clock: Clock,
        settings: Settings,
    ) -> None:
        self.db, self.storage, self.queue, self.clock, self.s = db, storage, queue, clock, settings

    # ---------------------------------------------------------------- access

    async def owned(
        self, actor: User, session_id: uuid.UUID, *, for_update: bool = False
    ) -> Session:
        stmt = select(Session).where(Session.id == session_id)
        if actor.role is not Role.ADMIN:
            stmt = stmt.where(Session.user_id == actor.id)
        if for_update:
            stmt = stmt.with_for_update()
        session = (await self.db.execute(stmt)).scalar_one_or_none()
        if session is None:
            raise NotFound("Session not found")
        return session

    async def files(self, session_id: uuid.UUID) -> Sequence[SessionFile]:
        stmt = (
            select(SessionFile)
            .where(SessionFile.session_id == session_id)
            .order_by(SessionFile.created_at)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def owner_of(self, session: Session) -> User:
        user = await self.db.get(User, session.user_id)
        assert user is not None
        return user

    # ---------------------------------------------------------------- upload

    async def upload(
        self, actor: User, files: list[UploadedFile], form: UploadForm, ctx: RequestContext
    ) -> list[Session]:
        if not files:
            raise ValidationFailed(fields={"files": "Choose at least one .json or .csv file"})
        if len(files) > self.s.max_upload_files:
            raise ValidationFailed(
                fields={"files": f"Upload at most {self.s.max_upload_files} files at once"}
            )
        owner = actor
        if form.user_id is not None and form.user_id != actor.id:
            if actor.role is not Role.ADMIN:
                raise Forbidden("Only administrators can upload for another user")
            target = await self.db.get(User, form.user_id)
            if target is None:
                raise NotFound("User not found")
            owner = target
        problems: dict[str, str] = {}
        for i, f in enumerate(files):
            label = f"files.{i}"
            if len(f.data) > self.s.max_upload_file_bytes:
                raise PayloadTooLarge(f"{_safe_name(f.name)} is larger than 50 MB")
            try:
                sniff(f.data)  # content first: gives the most specific message
            except ParserError as exc:
                problems[label] = f"{_safe_name(f.name)}: {exc}"
                continue
            if not _safe_name(f.name).lower().endswith(ALLOWED_EXTENSIONS):
                problems[label] = f"{_safe_name(f.name)}: only .json and .csv files are supported"
        if problems:
            # Reasons only (no file content); helps when the browser message isn't visible.
            log.info("upload_rejected", extra={"reasons": " | ".join(problems.values())[:500]})
            raise ValidationFailed("Some files can't be analysed", fields=problems)

        now = self.clock.now()
        stored: list[str] = []
        created: list[Session] = []
        try:
            for f in files:
                key = new_key()
                await self.storage.put(key, f.data)
                stored.append(key)
                session = Session(
                    id=uuid.uuid4(),
                    user_id=owner.id,
                    uploaded_by_id=actor.id,
                    type=form.type,
                    device=form.device,
                    recorded_at=form.recorded_at or now,
                    recorded_at_source=ValueSource.FORM
                    if form.recorded_at
                    else ValueSource.UPLOAD_TIME,
                    age=form.age,
                    age_source=ValueSource.FORM if form.age else ValueSource.UNKNOWN,
                    hr_max_manual=form.hr_max_manual,
                    notes=form.notes,
                    file_name=_safe_name(f.name),
                    status=SessionStatus.PROCESSING,
                    attempts=0,
                )
                self.db.add(session)
                self.db.add(
                    SessionFile(
                        session_id=session.id,
                        name=_safe_name(f.name),
                        size_bytes=len(f.data),
                        sha256=hashlib.sha256(f.data).hexdigest(),
                        storage_key=key,
                    )
                )
                created.append(session)
            await self.db.flush()
            for session in created:
                audit.record(
                    self.db,
                    action="session.uploaded",
                    now=now,
                    actor_id=actor.id,
                    target_id=owner.id,
                    ip=ctx.ip,
                    details={"session_id": str(session.id)},
                )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            for key in stored:  # no orphaned files
                await self.storage.delete(key)
            raise
        for session in created:
            await self.queue.enqueue(session.id, 0)
        for session in created:
            await self.db.refresh(session)
        return created

    # ---------------------------------------------------------------- reads

    def _scoped(self, actor: User, flt: ListFilter) -> Select[tuple[Session, User]]:
        stmt = select(Session, User).join(User, User.id == Session.user_id)
        if actor.role is not Role.ADMIN:
            stmt = stmt.where(Session.user_id == actor.id)  # never widened by a parameter
        elif flt.user_id is not None:
            stmt = stmt.where(Session.user_id == flt.user_id)
        if flt.status is not None:
            stmt = stmt.where(Session.status == flt.status)
        if flt.q:
            term = (
                "%"
                + flt.q.strip()
                .lower()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
                + "%"
            )
            stmt = stmt.where(
                or_(
                    func.lower(Session.file_name).like(term, escape="\\"),
                    func.lower(cast(Session.type, String)).like(term, escape="\\"),
                    func.lower(Session.notes).like(term, escape="\\"),
                    func.lower(User.email).like(term, escape="\\"),
                    func.lower(func.concat(User.first_name, " ", User.last_name)).like(
                        term, escape="\\"
                    ),
                )
            )
        return stmt

    async def list(
        self, actor: User, flt: ListFilter, *, limit: int, offset: int
    ) -> tuple[list[tuple[Session, User]], int, dict[str, Any]]:
        base = self._scoped(actor, flt)
        sub = base.subquery()
        agg = (
            await self.db.execute(
                select(
                    func.count(),
                    func.count(func.distinct(sub.c.user_id)),
                    func.coalesce(func.sum(sub.c.duration_s), 0.0),
                    func.avg(sub.c.rmssd),
                ).select_from(sub)
            )
        ).one()
        rows = (
            await self.db.execute(
                base.order_by(Session.recorded_at.desc(), Session.id).limit(limit).offset(offset)
            )
        ).all()
        stats = {
            "sessions": int(agg[0]),
            "users": int(agg[1]),
            "recorded_time_s": float(agg[2]),
            "avg_rmssd": round(float(agg[3]), 2) if agg[3] is not None else None,
        }
        return [(r[0], r[1]) for r in rows], int(agg[0]), stats

    async def result(self, actor: User, session_id: uuid.UUID) -> tuple[Session, AnalysisResult]:
        session = await self.owned(actor, session_id)
        if session.status is not SessionStatus.READY:
            raise NotReady(
                "The analysis failed — see the session's error"
                if session.status is SessionStatus.FAILED
                else "The analysis is still running"
            )
        result = await self.db.get(AnalysisResult, session_id)
        if result is None:
            raise NotReady()
        return session, result

    async def original_file(
        self, actor: User, session_id: uuid.UUID, file_id: uuid.UUID
    ) -> tuple[SessionFile, bytes]:
        await self.owned(actor, session_id)
        f = await self.db.get(SessionFile, file_id)
        if f is None or f.session_id != session_id:
            raise NotFound("File not found")
        return f, await self.storage.get(f.storage_key)

    # ---------------------------------------------------------------- changes

    async def delete(self, actor: User, session_id: uuid.UUID, ctx: RequestContext) -> None:
        session = await self.owned(actor, session_id, for_update=True)
        keys = [f.storage_key for f in await self.files(session.id)]
        owner = await self.owner_of(session)
        await self.db.delete(session)
        audit.record(
            self.db,
            action="session.deleted",
            now=self.clock.now(),
            actor_id=actor.id,
            target_id=owner.id,
            ip=ctx.ip,
            details={"session_id": str(session_id)},
        )
        if owner.hr_max_method is HrMaxMethod.PEAK:
            await self.db.flush()
            await recompute_user_zones(self.db, owner.id)
        await self.db.commit()
        for key in keys:  # after commit: a failed DB delete never loses files
            try:
                await self.storage.delete(key)
            except OSError:
                log.warning("storage_delete_failed", extra={"session_id": str(session_id)})

    async def retry(self, actor: User, session_id: uuid.UUID, ctx: RequestContext) -> Session:
        session = await self.owned(actor, session_id, for_update=True)
        if session.status is not SessionStatus.FAILED:
            raise Conflict("Only failed sessions can be retried", code="not_failed")
        session.status, session.error = SessionStatus.PROCESSING, None
        attempt = session.attempts
        audit.record(
            self.db,
            action="session.retried",
            now=self.clock.now(),
            actor_id=actor.id,
            target_id=session.user_id,
            ip=ctx.ip,
            details={"session_id": str(session_id)},
        )
        await self.db.commit()
        await self.queue.enqueue(session.id, attempt)
        await self.db.refresh(session)
        return session

    async def reanalyse_advanced(
        self, actor: User, session_id: uuid.UUID, options: dict[str, Any], ctx: RequestContext
    ) -> AnalysisResult:
        """Re-run the advanced HRV analysis with new options from the stored beats (no ECG
        reprocessing) and persist it, so the screens and the PDF show the same result."""
        import asyncio

        import numpy as np

        from netribeat.analysis.advanced import AdvancedOptions, analyse_advanced

        session, result = await self.result(actor, session_id)
        try:
            opts = AdvancedOptions(**options).validated()
        except ValueError as exc:
            raise ValidationFailed(str(exc), fields={"options": str(exc)}) from None
        sig = result.signals
        t = np.asarray(sig.get("beatTimesS", []), dtype=float)
        rr = np.asarray(sig.get("rrRawMs", []), dtype=float)
        adv = await asyncio.to_thread(analyse_advanced, t, rr, opts)
        result.metrics = {**result.metrics, "advanced": adv.metrics}
        result.signals = {**result.signals, "advanced": adv.series}
        audit.record(
            self.db,
            action="session.reanalysed",
            now=self.clock.now(),
            actor_id=actor.id,
            target_id=session.user_id,
            ip=ctx.ip,
            details={
                "session_id": str(session_id),
                "correction": opts.correction,
                "sample_start_s": opts.sample_start_s,
            },
        )
        await self.db.commit()
        return result

    # ---------------------------------------------------------------- HRmax settings

    async def hr_max_settings(self, target: User) -> dict[str, Any]:
        peak = await user_peak_hr(self.db, target.id)
        ready = int(
            (
                await self.db.execute(
                    select(func.count()).where(
                        Session.user_id == target.id, Session.status == SessionStatus.READY
                    )
                )
            ).scalar_one()
        )
        options = [
            {
                "method": "age",
                "value": (210 - target.age) if target.age else None,
                "detail": f"210 − age (age {target.age}); each session uses the age at recording"
                if target.age
                else "Uses each session's age at recording; set your age in Overview",
            },
            {
                "method": "peak",
                "value": round(peak) if peak else None,
                "detail": "Highest max HR across your reliable sessions"
                if peak
                else "No reliable ready sessions yet",
            },
            {
                "method": "manual",
                "value": target.hr_max_manual,
                "detail": "Entered by you (100–230 bpm)",
            },
        ]
        current = target.hr_max_method.value if target.hr_max_method else None
        effective = next((o for o in options if o["method"] == current), None)
        return {
            "method": current,
            "manual_value": target.hr_max_manual,
            "options": options,
            "effective": effective,
            "sessions_ready": ready,
        }

    async def set_hr_max(
        self,
        actor: User,
        target: User,
        *,
        method: str,
        manual_value: int | None,
        ctx: RequestContext,
    ) -> dict[str, Any]:
        if actor.id != target.id and actor.role is not Role.ADMIN:
            raise NotFound("User not found")
        try:
            chosen = HrMaxMethod(method)
        except ValueError:
            raise ValidationFailed(fields={"method": "Choose age, peak or manual"}) from None
        if chosen is HrMaxMethod.MANUAL:
            if manual_value is None or not 100 <= manual_value <= 230:
                raise ValidationFailed(
                    fields={"manualValue": "Enter a max HR between 100 and 230 bpm"}
                )
            target.hr_max_manual = manual_value
        elif chosen is HrMaxMethod.PEAK and await user_peak_hr(self.db, target.id) is None:
            raise ValidationFailed(
                fields={"method": "No reliable ready sessions to take a peak from yet"}
            )
        target.hr_max_method = chosen
        await self.db.flush()
        count = await recompute_user_zones(self.db, target.id)  # this user only
        audit.record(
            self.db,
            action="user.hr_max_changed",
            now=self.clock.now(),
            actor_id=actor.id,
            target_id=target.id,
            ip=ctx.ip,
            details={"method": chosen.value, "recomputed": count},
        )
        await self.db.commit()
        out = await self.hr_max_settings(target)
        out["recomputed_sessions"] = count
        return out
