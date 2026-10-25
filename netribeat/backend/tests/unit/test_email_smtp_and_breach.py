from __future__ import annotations

from typing import Any

import pytest

from netribeat.auth.password_policy import HibpRangeChecker
from netribeat.config import EmailBackend
from netribeat.email import service as email_service
from netribeat.email.service import (
    ConsoleEmailSender,
    FileEmailSender,
    MemoryEmailSender,
    OutgoingEmail,
    SmtpEmailSender,
    build_email_sender,
    deliver,
)
from tests.conftest import make_settings

MSG = OutgoingEmail("to@example.org", "Subject", "Body text", "verify_email")


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(self, host: str, port: int, timeout: float, **kw: Any) -> None:
        self.host, self.port, self.calls = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *a: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: object) -> None:
        self.calls.append("starttls")

    def login(self, user: str, pw: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, mime: Any) -> None:
        self.calls.append(f"send:{mime['To']}:{mime['Subject']}")


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakeSMTP.instances.clear()


async def test_smtp_starttls_login_and_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    s = make_settings(
        email_backend=EmailBackend.SMTP,
        smtp_host="smtp.example.org",
        smtp_username="mailer",
        smtp_password="pw-from-secret-store",
    )
    await SmtpEmailSender(s).send(MSG)
    (smtp,) = FakeSMTP.instances
    assert smtp.host == "smtp.example.org" and smtp.port == 587
    assert smtp.calls == ["starttls", "login:mailer", "send:to@example.org:Subject", "quit"]


async def test_smtp_implicit_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", FakeSMTP)
    s = make_settings(
        email_backend=EmailBackend.SMTP, smtp_host="smtp.example.org", smtp_ssl=True, smtp_port=465
    )
    await SmtpEmailSender(s).send(MSG)
    assert FakeSMTP.instances[0].calls == ["send:to@example.org:Subject", "quit"]


def test_build_sender_by_backend() -> None:
    assert isinstance(
        build_email_sender(make_settings(email_backend=EmailBackend.MEMORY)), MemoryEmailSender
    )
    assert isinstance(
        build_email_sender(make_settings(email_backend=EmailBackend.CONSOLE)), ConsoleEmailSender
    )
    assert isinstance(
        build_email_sender(make_settings(email_backend=EmailBackend.FILE)), FileEmailSender
    )
    assert isinstance(
        build_email_sender(make_settings(email_backend=EmailBackend.SMTP, smtp_host="h")),
        SmtpEmailSender,
    )


async def test_console_sender_writes_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    await ConsoleEmailSender("NetriBeat <x@y>").send(MSG)
    assert "DEV EMAIL" in capsys.readouterr().out


async def test_deliver_swallows_failures(caplog: pytest.LogCaptureFixture) -> None:
    class Broken:
        async def send(self, message: OutgoingEmail) -> None:
            raise OSError("smtp down")

    await deliver(Broken(), MSG)
    assert "email_delivery_failed" in caplog.text
    assert "to@example.org" not in caplog.text


async def test_hibp_detects_breached(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    digest = hashlib.sha1(b"hunter2hunter2", usedforsecurity=False).hexdigest().upper()
    checker = HibpRangeChecker()
    seen: list[str] = []

    def fake_fetch(prefix: str) -> str:
        seen.append(prefix)
        return f"{digest[5:]}:42\r\n0000000000000000000000000000000000A:1"

    monkeypatch.setattr(checker, "_fetch", fake_fetch)
    assert await checker.is_breached("hunter2hunter2")
    assert seen == [digest[:5]]  # only the 5-char prefix leaves the server
    assert not await checker.is_breached("a completely different phrase")


async def test_hibp_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    checker = HibpRangeChecker()

    def boom(prefix: str) -> str:
        raise OSError("offline")

    monkeypatch.setattr(checker, "_fetch", boom)
    assert await checker.is_breached("anything at all") is False
