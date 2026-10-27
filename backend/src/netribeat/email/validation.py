"""Shared email normaliser (CLAUDE.md: strip().lower(), once, at the boundary)."""

from __future__ import annotations

from email_validator import EmailNotValidError, validate_email

MAX_EMAIL_LENGTH = 254
INVALID_EMAIL_MESSAGE = "Enter a valid email address, like name@institute.org"


def normalise_email(raw: str) -> str:
    return raw.strip().lower()


def validated_email(raw: str) -> str:
    """Normalise and check syntax (no DNS lookups). Raises ValueError with the UI message."""
    email = normalise_email(raw)
    if not email or len(email) > MAX_EMAIL_LENGTH:
        raise ValueError(INVALID_EMAIL_MESSAGE)
    try:
        result = validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(INVALID_EMAIL_MESSAGE) from exc
    # validate_email may normalise unicode in the domain; lower-case again for consistency.
    return result.normalized.lower()
