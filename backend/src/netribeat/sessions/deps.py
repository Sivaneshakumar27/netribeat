"""Dependency wiring for sessions."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from netribeat.auth.deps import ClockDep, DbDep, SettingsDep
from netribeat.core.storage import Storage
from netribeat.sessions.jobs import JobQueue
from netribeat.sessions.service import SessionService


def get_storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


def get_queue(request: Request) -> JobQueue:
    queue: JobQueue = request.app.state.job_queue
    return queue


def get_session_service(
    db: DbDep,
    clock: ClockDep,
    settings: SettingsDep,
    storage: Annotated[Storage, Depends(get_storage)],
    queue: Annotated[JobQueue, Depends(get_queue)],
) -> SessionService:
    return SessionService(db=db, storage=storage, queue=queue, clock=clock, settings=settings)


SessionServiceDep = Annotated[SessionService, Depends(get_session_service)]
