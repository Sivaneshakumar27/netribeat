"""Password policy (NIST SP 800-63B style): length, a common-password blocklist, no
reuse of the person's own email or name, and an optional breached-password check.

No composition rules (e.g. "one symbol"); length and blocklists do more for security.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import urllib.request
from dataclasses import dataclass
from importlib import resources
from typing import Protocol

log = logging.getLogger(__name__)


def _load_common() -> frozenset[str]:
    text = resources.files("netribeat.auth").joinpath("common_passwords.txt").read_text("utf-8")
    return frozenset(
        line.strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    )


COMMON_PASSWORDS = _load_common()


class BreachedPasswordChecker(Protocol):
    async def is_breached(self, password: str) -> bool: ...


class NoBreachCheck:
    async def is_breached(self, password: str) -> bool:
        return False


class HibpRangeChecker:
    """Have I Been Pwned range API (k-anonymity: only the first 5 SHA-1 hex chars leave
    the server). Fails open with a warning so an outage can't block every sign-up."""

    URL = "https://api.pwnedpasswords.com/range/"

    def __init__(self, timeout_s: float = 3.0) -> None:
        self._timeout = timeout_s

    async def is_breached(self, password: str) -> bool:
        digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]
        try:
            body = await asyncio.to_thread(self._fetch, prefix)
        except OSError:
            log.warning("breach_check_unavailable")
            return False
        return any(line.split(":", 1)[0] == suffix for line in body.splitlines())

    def _fetch(self, prefix: str) -> str:
        req = urllib.request.Request(  # noqa: S310 — fixed https URL
            self.URL + prefix, headers={"Add-Padding": "true", "User-Agent": "NetriBeat"}
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310
            data: bytes = resp.read()
        return data.decode("utf-8", "replace")


@dataclass(frozen=True)
class PasswordPolicy:
    min_length: int
    max_length: int

    def problems(
        self, password: str, *, email: str | None = None, names: tuple[str | None, ...] = ()
    ) -> str | None:
        """Return a user-facing message for the first problem, or None if acceptable."""
        if len(password) < self.min_length:
            return f"Use at least {self.min_length} characters"
        if len(password) > self.max_length:
            return f"Use at most {self.max_length} characters"
        if not password.strip():
            return "Password can't be only spaces"
        lowered = password.lower()
        if lowered in COMMON_PASSWORDS:
            return "This password is too common. Choose something harder to guess"
        if len(set(lowered)) < 4:
            return "Use a password with more variety"
        if email:
            local = email.split("@", 1)[0].lower()
            if len(local) >= 4 and local in lowered:
                return "Don't include your email address in your password"
        for name in names:
            if name and len(name) >= 4 and name.lower() in lowered:
                return "Don't include your name in your password"
        return None
