"""`netribeat` command-line tool: the only way to provision administrators.

Run on the server (or in the backend container) with DATABASE_URL etc. set:

    uv run netribeat create-admin --email ops@example.org --first-name Ada --last-name Lovelace
    uv run netribeat set-role --email someone@example.org --role user
    uv run netribeat disable-user --email someone@example.org
    uv run netribeat cleanup

Passwords are read with getpass (never echoed, never accepted as an argument, so they
don't land in shell history or the process list). `--password-stdin` is for automated
bootstrap (e.g. `cat /run/secrets/admin_pw | netribeat create-admin ... --password-stdin`).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Callable, Sequence
from typing import TextIO

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from netribeat.audit import service as audit
from netribeat.auth.password_policy import PasswordPolicy
from netribeat.auth.security import hash_password
from netribeat.auth.service import cleanup_expired, revoke_user_sessions
from netribeat.clock import Clock, SystemClock
from netribeat.config import ABSOLUTE_MIN_PASSWORD_LENGTH
from netribeat.core.emails import validated_email
from netribeat.db import make_engine, make_sessionmaker
from netribeat.users import repository as users_repo
from netribeat.users.models import Role, User, UserSource


class CliSettings(BaseSettings):
    """What the admin commands need: the database and the password policy. Unlike the web
    app, the CLI never needs JWT_SECRET or OTP_PEPPER (it issues no tokens or codes), so an
    operator can run it with only DATABASE_URL, e.g. against a hosted database."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    database_url: str
    password_min_length: int = Field(default=12, ge=ABSOLUTE_MIN_PASSWORD_LENGTH)
    password_max_length: int = 128


def get_cli_settings() -> CliSettings:
    return CliSettings()  # DATABASE_URL comes from the environment or .env


class CliError(Exception):
    """A user-facing CLI failure (exit code 1, message on stderr)."""


def read_new_password(
    policy: PasswordPolicy,
    *,
    email: str,
    names: tuple[str | None, ...],
    from_stdin: bool,
    stdin: TextIO | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
) -> str:
    if from_stdin:
        password = (stdin or sys.stdin).readline().rstrip("\r\n")
    else:
        password = prompt("New password: ")
        if prompt("Repeat password: ") != password:
            raise CliError("Passwords don't match")
    problem = policy.problems(password, email=email, names=names)
    if problem:
        raise CliError(f"Password rejected: {problem}")
    return password


async def create_admin(
    db: AsyncSession,
    clock: Clock,
    *,
    email: str,
    first_name: str,
    last_name: str,
    password: str,
) -> User:
    """Create an admin with a password, or give an existing password-less user (created
    by an admin, upload or import) a password and the admin role."""
    now = clock.now()
    user = await users_repo.get_by_email(db, email, for_update=True)
    if user is not None and user.has_password:
        raise CliError("User already has a login; use forgot password or set-role")
    if user is None:
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            source=UserSource.ADMIN,
            token_version=0,
            is_active=True,
        )
        users_repo.add(db, user)
    user.role = Role.ADMIN
    user.password_hash = hash_password(password)
    # The operator provisioning on the server vouches for the address.
    user.email_verified_at = user.email_verified_at or now
    user.is_active = True
    await db.flush()
    audit.record(
        db, action="cli.admin_provisioned", now=now, target_id=user.id, details={"via": "cli"}
    )
    await db.commit()
    return user


async def create_user(
    db: AsyncSession, clock: Clock, *, email: str, first_name: str, last_name: str
) -> User:
    if await users_repo.get_by_email(db, email) is not None:
        raise CliError("A user with this email already exists")
    user = User(
        email=email,
        first_name=first_name,
        last_name=last_name,
        role=Role.USER,
        source=UserSource.ADMIN,
        token_version=0,
        is_active=True,
    )
    users_repo.add(db, user)
    await db.flush()
    audit.record(
        db, action="cli.user_created", now=clock.now(), target_id=user.id, details={"via": "cli"}
    )
    await db.commit()
    return user


async def _locked(db: AsyncSession, email: str) -> User:
    user = await users_repo.get_by_email(db, email, for_update=True)
    if user is None:
        raise CliError("No user with this email")
    return user


async def set_role(db: AsyncSession, clock: Clock, *, email: str, role: Role) -> User:
    user = await _locked(db, email)
    if user.role is role:
        return user
    if user.role is Role.ADMIN and user.is_active and await users_repo.count_active_admins(db) <= 1:
        raise CliError("Refusing to demote the last active admin")
    now = clock.now()
    previous = user.role
    user.role = role
    user.token_version += 1
    await revoke_user_sessions(db, user.id, now=now, reason="role_changed")
    audit.record(
        db,
        action="cli.role_changed",
        now=now,
        target_id=user.id,
        details={"via": "cli", "from": previous.value, "to": role.value},
    )
    await db.commit()
    return user


async def set_active(db: AsyncSession, clock: Clock, *, email: str, active: bool) -> User:
    user = await _locked(db, email)
    if user.is_active == active:
        return user
    if not active and user.role is Role.ADMIN and await users_repo.count_active_admins(db) <= 1:
        raise CliError("Refusing to disable the last active admin")
    now = clock.now()
    user.is_active = active
    user.token_version += 1
    await revoke_user_sessions(db, user.id, now=now, reason="disabled" if not active else "enabled")
    audit.record(
        db,
        action="cli.user_enabled" if active else "cli.user_disabled",
        now=now,
        target_id=user.id,
        details={"via": "cli"},
    )
    await db.commit()
    return user


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="netribeat", description="NetriBeat administration")
    sub = p.add_subparsers(dest="command", required=True)

    ca = sub.add_parser("create-admin", help="Provision an administrator (prompts for password)")
    ca.add_argument("--email", required=True)
    ca.add_argument("--first-name", required=True)
    ca.add_argument("--last-name", required=True)
    ca.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from the first line of stdin (automation)",
    )

    cu = sub.add_parser("create-user", help="Create a user without a password (invite)")
    cu.add_argument("--email", required=True)
    cu.add_argument("--first-name", required=True)
    cu.add_argument("--last-name", required=True)

    sr = sub.add_parser("set-role", help="Change a role; signs the user out everywhere")
    sr.add_argument("--email", required=True)
    sr.add_argument("--role", required=True, choices=[r.value for r in Role])

    for name, help_text in (
        ("disable-user", "Disable an account and sign it out"),
        ("enable-user", "Re-enable an account"),
    ):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--email", required=True)

    cf = sub.add_parser("check-file", help="Check whether recording files can be analysed")
    cf.add_argument("paths", nargs="+", help="One or more .json / .csv files")

    sub.add_parser("list-admins", help="List administrator accounts")
    sub.add_parser("cleanup", help="Expire challenges and delete stale sign-ups/sessions")
    return p


async def _run(
    args: argparse.Namespace,
    settings: CliSettings,
    maker: async_sessionmaker[AsyncSession],
    clock: Clock,
    out: TextIO,
) -> None:
    policy = PasswordPolicy(settings.password_min_length, settings.password_max_length)

    def email_arg() -> str:
        try:
            return validated_email(args.email)
        except ValueError as exc:
            raise CliError(str(exc)) from None

    async with maker() as db:
        match args.command:
            case "create-admin":
                email = email_arg()
                password = read_new_password(
                    policy,
                    email=email,
                    names=(args.first_name, args.last_name),
                    from_stdin=args.password_stdin,
                )
                user = await create_admin(
                    db,
                    clock,
                    email=email,
                    first_name=args.first_name,
                    last_name=args.last_name,
                    password=password,
                )
                out.write(f"Admin ready: id={user.id}\n")
            case "create-user":
                user = await create_user(
                    db,
                    clock,
                    email=email_arg(),
                    first_name=args.first_name,
                    last_name=args.last_name,
                )
                out.write(f"User created: id={user.id} (sets a password via Forgot password)\n")
            case "set-role":
                user = await set_role(db, clock, email=email_arg(), role=Role(args.role))
                out.write(f"Role is now {user.role.value}: id={user.id}\n")
            case "disable-user" | "enable-user":
                active = args.command == "enable-user"
                user = await set_active(db, clock, email=email_arg(), active=active)
                out.write(f"{'Enabled' if active else 'Disabled'}: id={user.id}\n")
            case "list-admins":
                rows, _ = await users_repo.list_users(
                    db,
                    users_repo.UserFilter(role=Role.ADMIN),
                    sort=users_repo.UserSort.CREATED_ASC,
                    limit=200,
                    offset=0,
                )
                for u in rows:
                    out.write(f"{u.id}  {u.email}  {'active' if u.is_active else 'disabled'}\n")
            case "cleanup":
                out.write(f"{await cleanup_expired(db, clock.now())}\n")


def check_files(paths: Sequence[str], out: TextIO) -> int:
    """Run the real parser and analysis on local files and explain the result.
    Needs no database or settings. Returns the number of files that failed."""
    from pathlib import Path

    from netribeat.analysis.pipeline import analyse
    from netribeat.parsers.base import ParserError
    from netribeat.parsers.registry import parse_file

    failed = 0
    for p in paths:
        path = Path(p)
        out.write(f"\n{path.name}\n")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            out.write(f"  cannot read the file: {exc.strerror}\n")
            failed += 1
            continue
        if path.suffix.lower() not in {".json", ".csv", ".txt"}:
            out.write("  NOTE: uploads accept only .json and .csv file names\n")
        try:
            rec = parse_file(path.name, raw)
        except ParserError as exc:
            out.write(f"  NOT SUPPORTED: {exc}\n")
            failed += 1
            continue
        m = analyse(rec).metrics
        out.write(f"  format: {rec.format} ({rec.kind.value}), duration {rec.duration_s:.0f} s")
        out.write(f", {rec.fs_hz:g} Hz" if rec.fs_hz else "")
        out.write(f", age in file: {rec.metadata['age']}\n" if "age" in rec.metadata else "\n")
        rel = m["reliability"]
        out.write(
            f"  quality: {m['quality']}, beat detection "
            f"{'reliable' if rel['reliable'] else 'UNRELIABLE'} "
            f"(coverage {rel['beatCoverage'] * 100:.0f} %)\n"
        )
        hr = m["hr"]
        if hr["avg"] is not None:
            out.write(f"  heart rate: avg {hr['avg']} bpm (min {hr['min']}, max {hr['max']})\n")
        if m["timeDomain"]:
            out.write(f"  RMSSD {m['timeDomain']['rmssd']} ms, SDNN {m['timeDomain']['sdnn']} ms\n")
        for w in m["warnings"]:
            out.write(f"  warning: {w}\n")
    return failed


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "check-file":  # works without a database or .env
        return 1 if check_files(args.paths, sys.stdout) else 0
    try:
        settings = get_cli_settings()
    except ValidationError:
        sys.stderr.write("error: set DATABASE_URL (environment variable or backend/.env)\n")
        return 1

    async def runner() -> None:
        engine = make_engine(settings.database_url)
        try:
            await _run(args, settings, make_sessionmaker(engine), SystemClock(), sys.stdout)
        finally:
            await engine.dispose()

    try:
        asyncio.run(runner())
    except CliError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
