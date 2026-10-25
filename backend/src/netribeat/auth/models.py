"""Authentication state: pending sign-ups, OTP/reset challenges and refresh sessions."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from netribeat.db import Base


class ChallengePurpose(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"  # noqa: S105 — enum value, not a secret


class PendingRegistration(Base):
    """A sign-up that has not proved control of its email yet. Never a usable account."""

    __tablename__ = "pending_registrations"
    __table_args__ = (Index("ix_pending_registrations_expires_at", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]


class AuthChallenge(Base):
    """A single-use OTP. Only an HMAC of the code is stored.

    For password reset, a successful OTP check issues a short-lived reset token
    (also stored only as an HMAC) that authorises exactly one password change.
    At most one *open* challenge exists per (purpose, email) — enforced by a partial
    unique index — so a new request supersedes the previous code.
    """

    __tablename__ = "auth_challenges"
    __table_args__ = (
        Index(
            "uq_auth_challenges_open",
            "purpose",
            "email",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
        Index("ix_auth_challenges_expires_at", "expires_at"),
        Index("ix_auth_challenges_email_created", "email", "created_at"),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    purpose: Mapped[ChallengePurpose] = mapped_column(
        Enum(
            ChallengePurpose,
            name="challenge_purpose",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    email: Mapped[str] = mapped_column(String(254))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    pending_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pending_registrations.id", ondelete="CASCADE")
    )
    code_hash: Mapped[str] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime]
    last_sent_at: Mapped[datetime]
    send_count: Mapped[int] = mapped_column(Integer, default=1)
    otp_verified_at: Mapped[datetime | None]
    reset_token_hash: Mapped[str | None] = mapped_column(String(128), unique=True)
    reset_token_expires_at: Mapped[datetime | None]
    # closed_at: consumed, superseded, exhausted or expired. Closed challenges never validate.
    closed_at: Mapped[datetime | None]
    close_reason: Mapped[str | None] = mapped_column(String(32))


class AuthSession(Base):
    """A signed-in browser/device. The refresh token (HttpOnly cookie) maps to one row.

    Access tokens carry this row's id (`sid`); revoking the row signs that device out
    immediately, even before the short-lived access token expires.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    refresh_token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    previous_refresh_token_hash: Mapped[str | None] = mapped_column(String(128))
    token_version: Mapped[int] = mapped_column(Integer)
    remember: Mapped[bool]
    created_at: Mapped[datetime]
    last_used_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    revoke_reason: Mapped[str | None] = mapped_column(String(32))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(64))
