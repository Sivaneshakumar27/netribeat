"""Dependency wiring for the users feature."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from netribeat.auth.deps import ClockDep, DbDep, OutboxDep, SettingsDep
from netribeat.users.service import UserService


def get_user_service(
    db: DbDep, clock: ClockDep, settings: SettingsDep, outbox: OutboxDep
) -> UserService:
    return UserService(db=db, clock=clock, settings=settings, outbox=outbox)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
