"""Drive `netribeat …` through main() exactly as the console script does (real commits)."""

from __future__ import annotations

import asyncio
import io
import uuid

import pytest
from sqlalchemy import text

from netribeat import cli
from netribeat.db import make_engine
from tests.conftest import STRONG_PASSWORD, TEST_DATABASE_URL, make_settings


async def _cleanup(tag: str) -> None:
    engine = make_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        p = {"p": f"%{tag}%"}
        await conn.execute(
            text(
                "DELETE FROM audit_events WHERE target_user_id IN "
                "(SELECT id FROM users WHERE email LIKE :p)"
            ),
            p,
        )
        await conn.execute(text("DELETE FROM users WHERE email LIKE :p"), p)
    await engine.dispose()


def test_cli_end_to_end(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tag = uuid.uuid4().hex[:8]
    admin, other = f"ops-{tag}@example.org", f"user-{tag}@example.org"
    monkeypatch.setattr(cli, "get_settings", lambda: make_settings())
    try:
        monkeypatch.setattr("sys.stdin", io.StringIO(STRONG_PASSWORD + "\n"))
        assert (
            cli.main(
                [
                    "create-admin",
                    "--email",
                    admin.upper(),
                    "--first-name",
                    "Op",
                    "--last-name",
                    "S",
                    "--password-stdin",
                ]
            )
            == 0
        )
        assert "Admin ready" in capsys.readouterr().out
        assert (
            cli.main(["create-user", "--email", other, "--first-name", "U", "--last-name", "V"])
            == 0
        )
        assert cli.main(["set-role", "--email", other, "--role", "admin"]) == 0
        assert cli.main(["disable-user", "--email", other]) == 0
        assert cli.main(["enable-user", "--email", other]) == 0
        assert cli.main(["list-admins"]) == 0
        out = capsys.readouterr().out
        assert admin in out and other in out
        assert cli.main(["cleanup"]) == 0
        # Errors are reported, not raised; exit code 1.
        monkeypatch.setattr("sys.stdin", io.StringIO(STRONG_PASSWORD + "\n"))
        assert (
            cli.main(
                [
                    "create-admin",
                    "--email",
                    admin,
                    "--first-name",
                    "O",
                    "--last-name",
                    "S",
                    "--password-stdin",
                ]
            )
            == 1
        )
        assert "already has a login" in capsys.readouterr().err
        assert cli.main(["disable-user", "--email", "not-an-email"]) == 1
        assert cli.main(["set-role", "--email", f"ghost-{tag}@example.org", "--role", "user"]) == 1
    finally:
        asyncio.run(_cleanup(tag))


def test_cli_has_no_password_argument() -> None:
    with pytest.raises(SystemExit):
        cli.main(
            [
                "create-admin",
                "--email",
                "a@x.org",
                "--first-name",
                "A",
                "--last-name",
                "B",
                "--password",
                "secret",
            ]
        )


def test_check_file_command(capsys: pytest.CaptureFixture[str], tmp_path: object) -> None:
    from pathlib import Path

    fix = Path(__file__).resolve().parents[1] / "fixtures" / "datasets"
    bad = Path(str(tmp_path)) / "notes.csv"
    bad.write_text("a,b\n1,2\n")
    code = cli.main(
        ["check-file", str(fix / "D4BLHRV_BLHR.csv"), str(fix / "D3BLHRV_BLHR.csv"), str(bad)]
    )
    out = capsys.readouterr().out
    assert code == 1  # one file unsupported
    assert "movesense_csv_ecg" in out and "age in file: 18" in out and "RMSSD 24.1 ms" in out
    assert "UNRELIABLE" in out  # D3
    assert "NOT SUPPORTED: Several columns but none is named RR" in out
