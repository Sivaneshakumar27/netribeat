"""Email delivery behind one interface.

* console / file: development only (Settings refuses them in production).
* smtp: real delivery through any SMTP provider (STARTTLS or implicit TLS).
* memory: tests inspect `sent`.

Messages are rendered from plain-text templates in `email/templates/`. They never
contain a password (master prompt §6 overrides any request to email credentials).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
import sys
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from importlib import resources
from pathlib import Path
from string import Template
from typing import Protocol

from netribeat.config import EmailBackend, Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    template: str


class EmailSender(Protocol):
    async def send(self, message: OutgoingEmail) -> None: ...


def render(template: str, **values: str) -> tuple[str, str]:
    """Return (subject, body). First line of the template is `Subject: …`."""
    raw = (
        resources.files("netribeat.email")
        .joinpath("templates", f"{template}.txt")
        .read_text("utf-8")
    )
    filled = Template(raw).substitute(**values)
    first, _, body = filled.partition("\n")
    if not first.startswith("Subject: "):
        raise ValueError(f"template {template} must start with 'Subject: '")
    return first.removeprefix("Subject: ").strip(), body.lstrip("\n")


def _to_mime(sender: str, msg: OutgoingEmail) -> EmailMessage:
    mime = EmailMessage()
    mime["From"] = sender
    mime["To"] = msg.to
    mime["Subject"] = msg.subject
    mime["Date"] = formatdate(localtime=False)
    mime["Message-ID"] = make_msgid(domain="netribeat")
    mime["Auto-Submitted"] = "auto-generated"
    mime.set_content(msg.text)
    return mime


class MemoryEmailSender:
    def __init__(self) -> None:
        self.sent: list[OutgoingEmail] = []

    async def send(self, message: OutgoingEmail) -> None:
        self.sent.append(message)


class ConsoleEmailSender:
    """Development: prints the whole message (including any OTP) to stdout, not to logs."""

    def __init__(self, sender: str) -> None:
        self._from = sender

    async def send(self, message: OutgoingEmail) -> None:
        sys.stdout.write(
            "\n"
            + "=" * 72
            + "\n[DEV EMAIL — not sent]\n"
            + _to_mime(self._from, message).as_string()
            + "=" * 72
            + "\n"
        )
        sys.stdout.flush()


class FileEmailSender:
    """Development: writes each message as an .eml file you can open in a mail client."""

    def __init__(self, sender: str, directory: Path) -> None:
        self._from = sender
        self._dir = directory

    async def send(self, message: OutgoingEmail) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{uuid.uuid4().hex}.eml"
        await asyncio.to_thread(path.write_bytes, _to_mime(self._from, message).as_bytes())


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        if not settings.smtp_host:
            raise ValueError("SMTP_HOST is required")
        self._s = settings
        self._host: str = settings.smtp_host

    async def send(self, message: OutgoingEmail) -> None:
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: OutgoingEmail) -> None:
        s = self._s
        mime = _to_mime(s.email_from, message)
        context = ssl.create_default_context()
        smtp: smtplib.SMTP
        if s.smtp_ssl:
            smtp = smtplib.SMTP_SSL(
                self._host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=context
            )
        else:
            smtp = smtplib.SMTP(self._host, s.smtp_port, timeout=s.smtp_timeout_seconds)
        with smtp:
            if not s.smtp_ssl and s.smtp_starttls:
                smtp.starttls(context=context)
            if s.smtp_username and s.smtp_password:
                smtp.login(s.smtp_username, s.smtp_password.get_secret_value())
            smtp.send_message(mime)


def build_email_sender(settings: Settings) -> EmailSender:
    match settings.email_backend:
        case EmailBackend.SMTP:
            return SmtpEmailSender(settings)
        case EmailBackend.FILE:
            return FileEmailSender(settings.email_from, settings.email_file_dir)
        case EmailBackend.MEMORY:
            return MemoryEmailSender()
        case EmailBackend.CONSOLE:
            return ConsoleEmailSender(settings.email_from)


async def deliver(sender: EmailSender, message: OutgoingEmail) -> None:
    """Background-task wrapper: delivery failures are logged (template name only), never raised
    into the request, so response timing and status don't reveal whether mail was sent."""
    try:
        await sender.send(message)
    except Exception:  # job boundary: log and continue
        log.exception("email_delivery_failed", extra={"template": message.template})
