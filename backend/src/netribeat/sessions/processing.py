"""Run the analysis for a stored session and persist the result. Used by the Arq worker
and the in-process (development) queue. Also recomputes HRmax-dependent zone metrics.

Safe to retry: the session row is locked with FOR UPDATE SKIP LOCKED for the whole run,
so two workers never analyse the same session; a session that isn't `processing` is
left alone.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from netribeat.analysis.hr import resolve_hr_max, zone_metrics
from netribeat.analysis.pipeline import analyse
from netribeat.clock import Clock
from netribeat.core.storage import Storage
from netribeat.parsers.base import ParserError
from netribeat.parsers.registry import parse_file
from netribeat.sessions.models import (
    AnalysisResult,
    Session,
    SessionFile,
    SessionStatus,
    ValueSource,
)
from netribeat.users.models import User

log = logging.getLogger(__name__)
GENERIC_FAILURE = "Analysis failed unexpectedly. Retry, or contact your administrator."


async def user_peak_hr(db: AsyncSession, user_id: uuid.UUID) -> float | None:
    """Highest max HR among the user's ready sessions whose beat detection is reliable
    and whose quality isn't no_ecg (the "valid" sessions)."""
    stmt = select(func.max(Session.max_hr)).where(
        Session.user_id == user_id,
        Session.status == SessionStatus.READY,
        Session.reliable.is_(True),
        Session.quality != "no_ecg",
    )
    value = (await db.execute(stmt)).scalar_one_or_none()
    return float(value) if value is not None else None


def _zones_for(
    session: Session, user: User, peak: float | None, bpm: list[float]
) -> dict[str, Any]:
    hr_max = resolve_hr_max(
        user_method=user.hr_max_method.value if user.hr_max_method else None,
        user_manual=user.hr_max_manual,
        user_peak=peak,
        session_override=session.hr_max_manual,
        age_at_recording=session.age,  # age at recording, never today's age
    )
    return zone_metrics(np.asarray(bpm, dtype=np.float64), hr_max)


async def recompute_user_zones(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Re-apply HRmax to every ready session of ONE user from the stored 1 Hz series.
    Runs in the caller's transaction; no ECG reprocessing."""
    user = await db.get(User, user_id)
    if user is None:
        return 0
    peak = await user_peak_hr(db, user_id)
    rows = (
        await db.execute(
            select(Session, AnalysisResult)
            .join(AnalysisResult, AnalysisResult.session_id == Session.id)
            .where(Session.user_id == user_id, Session.status == SessionStatus.READY)
            .with_for_update(of=AnalysisResult)
        )
    ).all()
    for session, result in rows:
        zones = _zones_for(session, user, peak, result.signals.get("hr", {}).get("bpm", []))
        result.metrics.update(zones)
        flag_modified(result, "metrics")
        session.training_load = zones["trainingLoad"]
    return len(rows)


async def process_session(
    maker: async_sessionmaker[AsyncSession],
    storage: Storage,
    clock: Clock,
    session_id: uuid.UUID,
    *,
    timeout_s: float = 600,
) -> None:
    async with maker() as db:
        session = (
            await db.execute(
                select(Session).where(Session.id == session_id).with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if session is None or session.status is not SessionStatus.PROCESSING:
            return
        session.attempts += 1
        file = (
            (await db.execute(select(SessionFile).where(SessionFile.session_id == session_id)))
            .scalars()
            .first()
        )
        try:
            if file is None:
                raise ParserError("The session has no file")
            raw = await storage.get(file.storage_key)
            parsed = await asyncio.wait_for(
                asyncio.to_thread(parse_file, file.name, raw), timeout_s
            )
            core = await asyncio.wait_for(asyncio.to_thread(analyse, parsed), timeout_s)
        except ParserError as exc:
            await _fail(db, session, str(exc), clock.now())
            return
        except TimeoutError:
            await _fail(db, session, "Analysis took too long and was stopped", clock.now())
            return
        except Exception:  # job boundary: keep details server-side
            log.exception("analysis_failed", extra={"session_id": str(session_id)})
            await _fail(db, session, GENERIC_FAILURE, clock.now())
            return

        file.kind = parsed.kind.value
        file.format = parsed.format
        meta = parsed.metadata
        file_age = meta.get("age")
        if session.age is not None and isinstance(file_age, int) and file_age != session.age:
            core.metrics["warnings"].append(
                f"The age entered at upload ({session.age}) differs from the age in the file "
                f"header ({file_age}); the entered age is used"
            )
        if session.age is None and isinstance(meta.get("age"), int) and 8 <= meta["age"] <= 100:
            session.age, session.age_source = meta["age"], ValueSource.FILE
        if session.recorded_at_source is ValueSource.UPLOAD_TIME and meta.get("recorded_at"):
            session.recorded_at = datetime.fromisoformat(meta["recorded_at"])
            session.recorded_at_source = ValueSource.FILE

        m = core.metrics
        session.status = SessionStatus.READY
        session.error = None
        session.processed_at = clock.now()
        session.quality = m["quality"]
        session.reliable = m["reliability"]["reliable"]
        session.duration_s = m["source"]["durationS"]
        session.avg_hr, session.max_hr = m["hr"]["avg"], m["hr"]["max"]
        session.rmssd = m["timeDomain"]["rmssd"] if m["timeDomain"] else None
        session.artefact_count = m["beats"]["artefacts"]
        session.artefact_pct = m["beats"]["artefactPct"]
        await db.flush()  # this session now counts towards the user's peak

        user = await db.get(User, session.user_id)
        assert user is not None
        zones = _zones_for(
            session, user, await user_peak_hr(db, user.id), core.signals["hr"]["bpm"]
        )
        m.update(zones)
        session.training_load = zones["trainingLoad"]
        existing = await db.get(AnalysisResult, session_id)
        if existing is None:
            db.add(
                AnalysisResult(
                    session_id=session_id,
                    analysis_version=m["analysisVersion"],
                    metrics=m,
                    signals=core.signals,
                )
            )
        else:
            existing.metrics, existing.signals = m, core.signals
            existing.analysis_version = m["analysisVersion"]
        if user.hr_max_method is not None and user.hr_max_method.value == "peak":
            await db.flush()
            await recompute_user_zones(db, user.id)  # a new peak changes every session
        await db.commit()


async def _fail(db: AsyncSession, session: Session, message: str, now: datetime) -> None:
    session.status = SessionStatus.FAILED
    session.error = message[:500]
    session.processed_at = now
    await db.commit()
