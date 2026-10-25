"""Background analysis jobs.

* ArqJobQueue: production. Jobs live in Redis; a separate worker process
  (``arq netribeat.sessions.worker.WorkerSettings``) runs them, retries up to 3 times
  and survives restarts. The job id is derived from the session id and attempt, so a
  duplicate enqueue for the same attempt is ignored by Arq.
* InlineJobQueue: development and tests: runs in the API process.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from arq.connections import ArqRedis

ProcessFn = Callable[[uuid.UUID], Coroutine[Any, Any, None]]


class JobQueue(Protocol):
    async def enqueue(self, session_id: uuid.UUID, attempt: int) -> None: ...


class ArqJobQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self.pool = pool

    async def enqueue(self, session_id: uuid.UUID, attempt: int) -> None:
        await self.pool.enqueue_job(
            "analyse_session", str(session_id), _job_id=f"analyse:{session_id}:{attempt}"
        )


class InlineJobQueue:
    """``wait=True`` (tests) finishes the analysis before the request returns;
    ``wait=False`` (development) runs it as a background task."""

    def __init__(self, process: ProcessFn, *, wait: bool) -> None:
        self.process = process
        self.wait = wait
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(self, session_id: uuid.UUID, attempt: int) -> None:
        if self.wait:
            await self.process(session_id)
            return
        task = asyncio.create_task(self.process(session_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
