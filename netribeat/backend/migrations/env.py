"""Alembic environment (async). Reads DATABASE_URL from the environment / .env."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import Connection

import netribeat.models  # noqa: F401  (registers every table)
from netribeat.db import Base, make_engine

config = context.config
if config.config_file_name is not None:
    from logging.config import fileConfig

    fileConfig(config.config_file_name)  # prints "Running upgrade …" lines
target_metadata = Base.metadata


class _DbOnly(BaseSettings):
    """Migrations need only the database URL — never the app's secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str


def _database_url() -> str:
    return os.environ.get("DATABASE_URL") or _DbOnly().database_url  # type: ignore[call-arg]


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = make_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
