"""The test session itself runs `downgrade base` + `upgrade head` (conftest). Here we
check that the models and migrations agree and that SQL scripts can be generated."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import run_alembic


async def test_models_match_migrations(engine: AsyncEngine) -> None:
    result = run_alembic("check")
    assert result.returncode == 0, result.stdout + result.stderr


async def test_offline_sql_for_full_upgrade_and_downgrade(engine: AsyncEngine) -> None:
    up = run_alembic("upgrade", "base:head", "--sql")
    assert up.returncode == 0, up.stderr
    assert "CREATE TABLE users" in up.stdout
    down = run_alembic("downgrade", "head:base", "--sql")
    assert down.returncode == 0, down.stderr
    assert "DROP TABLE users" in down.stdout


async def test_single_head(engine: AsyncEngine) -> None:
    heads = run_alembic("heads")
    assert heads.returncode == 0
    assert len([line for line in heads.stdout.splitlines() if line.strip()]) == 1
