from __future__ import annotations

from pathlib import Path

import pytest

from netribeat.email.service import FileEmailSender, OutgoingEmail, render

TEMPLATES = [
    "verify_email",
    "account_exists",
    "account_activated",
    "password_reset_code",
    "password_reset_done",
    "account_invited",
]
VALUES = dict(
    name="Ada",
    code="123456",
    minutes="10",
    login_url="http://x/login",
    email="a@x.org",
    when="2026-10-22 09:00",
    forgot_url="http://x/forgot",
)


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_template_renders_with_subject(template: str) -> None:
    subject, body = render(template, **VALUES)
    assert subject and body
    assert "$" not in body


@pytest.mark.parametrize("template", TEMPLATES)
def test_no_template_contains_a_password_placeholder(template: str) -> None:
    from importlib import resources

    raw = resources.files("netribeat.email").joinpath("templates", f"{template}.txt").read_text()
    assert "$password" not in raw.lower()


async def test_file_sender_writes_eml(tmp_path: Path) -> None:
    sender = FileEmailSender("NetriBeat <no-reply@test>", tmp_path)
    await sender.send(OutgoingEmail("a@x.org", "Hi", "Body", "t"))
    files = list(tmp_path.glob("*.eml"))
    assert len(files) == 1
    assert b"Subject: Hi" in files[0].read_bytes()
