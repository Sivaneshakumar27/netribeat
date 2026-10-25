"""Arq worker. Run with:  arq netribeat.sessions.worker.WorkerSettings

On start it re-queues sessions left in `processing` (e.g. the worker died mid-job), so
analysis is recoverable after a restart.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from arq.connections import RedisSettings
from sqlalchemy import select

from netribeat.clock import SystemClock
from netribeat.config import get_settings
from netribeat.core.storage import LocalStorage
from netribeat.db import make_engine, make_sessionmaker
from netribeat.logging_config import configure_logging
from netribeat.sessions.models import Session, SessionStatus
from netribeat.sessions.processing import process_session

log = logging.getLogger(__name__)
STUCK_AFTER = timedelta(minutes=15)


async def analyse_session(ctx: dict[str, Any], session_id: str) -> None:
    await process_session(
        ctx["maker"],
        ctx["storage"],
        ctx["clock"],
        uuid.UUID(session_id),
        timeout_s=ctx["settings"].analysis_timeout_seconds,
    )


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    ctx.update(
        settings=settings,
        engine=engine,
        maker=make_sessionmaker(engine),
        storage=LocalStorage(settings.storage_dir),
        clock=SystemClock(),
    )
    cutoff = ctx["clock"].now() - STUCK_AFTER
    async with ctx["maker"]() as db:
        stuck = (
            await db.execute(
                select(Session.id, Session.attempts).where(
                    Session.status == SessionStatus.PROCESSING, Session.updated_at < cutoff
                )
            )
        ).all()
    for sid, attempts in stuck:
        await ctx["redis"].enqueue_job(
            "analyse_session", str(sid), _job_id=f"analyse:{sid}:{attempts}:recovered"
        )
    if stuck:
        log.info("requeued_stuck_sessions", extra={"count": len(stuck)})


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [analyse_session]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
    job_timeout = get_settings().analysis_timeout_seconds + 60
    keep_result = 3600
