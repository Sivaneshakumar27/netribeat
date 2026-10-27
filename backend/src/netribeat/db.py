"""Async SQLAlchemy engine, declarative base and the session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import DateTime, MetaData, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: dict[Any, Any] = {datetime: DateTime(timezone=True)}


def make_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True, **kwargs)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# Databases created before 0004 named this column/type "sex"; rename in place (keeps values).
_RENAME_SEX_TO_GENDER = """
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name = 'users' AND column_name = 'sex') THEN
    ALTER TYPE sex RENAME TO gender;
    ALTER TABLE users RENAME COLUMN sex TO gender;
  END IF;
END $$;
"""


# Columns added after a table first shipped (create_all never alters existing tables).
_ADD_COLUMNS = """
ALTER TABLE recordings
  ADD COLUMN IF NOT EXISTS gender VARCHAR(10),
  ADD COLUMN IF NOT EXISTS resting_hr INTEGER,
  ADD COLUMN IF NOT EXISTS height_cm INTEGER,
  ADD COLUMN IF NOT EXISTS weight_kg DOUBLE PRECISION;
"""


async def init_db(engine: AsyncEngine) -> None:
    """Create any missing tables at startup (idempotent; existing tables are left alone)."""
    import netribeat.auth.models
    import netribeat.sessions.models  # noqa: F401  (registers every table)

    async with engine.begin() as conn:
        await conn.execute(text(_RENAME_SEX_TO_GENDER))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(_ADD_COLUMNS))


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Services commit explicitly; anything uncommitted rolls back."""
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with maker() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
