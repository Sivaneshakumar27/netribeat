"""Authentication business rules: registration with email OTP, login, sessions, password reset.

Design notes (see docs/security.md for the threat model):
* Responses never reveal whether an email has an account (register, resend,
  forgot-password all answer the same; failed logins share one 401 body).
* Argon2 runs on every login and registration path, so timing doesn't leak either.
* OTPs and reset/refresh tokens are stored only as HMAC-SHA256 with a server pepper.
* Each challenge is single-use, expires, and closes after `otp_max_attempts` failures;
  rows are locked (SELECT … FOR UPDATE) while being checked so they can't be raced.
* Emails are queued in an Outbox and delivered after the transaction commits.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.auth import audit
from netribeat.auth import repository as repo
from netribeat.auth import user_repository as users_repo
from netribeat.auth.models import (
    AuthChallenge,
    AuthSession,
    ChallengePurpose,
    Role,
    User,
    UserSource,
)
from netribeat.auth.password_policy import BreachedPasswordChecker, PasswordPolicy
from netribeat.auth.security import (
    TokenCodec,
    constant_time_equals,
    generate_opaque_token,
    generate_otp,
    hash_password,
    keyed_hash,
    password_needs_rehash,
    verify_password,
)
from netribeat.clock import Clock
from netribeat.config import Settings
from netribeat.core.errors import (
    BadRequest,
    Conflict,
    Forbidden,
    InvalidCredentials,
    NotFound,
    TooManyAttempts,
    Unauthorized,
    ValidationFailed,
)
from netribeat.core.ratelimit import RateLimiter
from netribeat.email.service import OutgoingEmail, render

log = logging.getLogger(__name__)

INVALID_CODE_MESSAGE = "The code is invalid or has expired. Request a new code if needed"
GENERIC_REGISTER_MESSAGE = "If this email can be registered, we've sent a verification code to it"
GENERIC_RESEND_MESSAGE = "If a sign-up is waiting for this email, we've sent a new code"
GENERIC_FORGOT_MESSAGE = "If an account exists for this email, we've sent a reset code"
REFRESH_REUSE_GRACE = timedelta(seconds=20)


@dataclass(frozen=True)
class RequestContext:
    ip: str | None
    user_agent: str | None


@dataclass
class Outbox:
    """Emails to deliver after commit. The router hands them to BackgroundTasks."""

    messages: list[OutgoingEmail] = field(default_factory=list)

    def add(self, message: OutgoingEmail) -> None:
        self.messages.append(message)


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    access_expires_at: datetime
    refresh_token: str | None  # None when the cookie must not change (reuse grace)
    session_expires_at: datetime
    remember: bool
    user: User


@dataclass(frozen=True)
class ResetAuthorisation:
    reset_token: str
    expires_at: datetime


class AuthService:
    def __init__(
        self,
        *,
        db: AsyncSession,
        settings: Settings,
        clock: Clock,
        limiter: RateLimiter,
        codec: TokenCodec,
        breach_checker: BreachedPasswordChecker,
        outbox: Outbox,
    ) -> None:
        self.db = db
        self.s = settings
        self.clock = clock
        self.limiter = limiter
        self.codec = codec
        self.breach = breach_checker
        self.outbox = outbox
        self.policy = PasswordPolicy(settings.password_min_length, settings.password_max_length)
        self._pepper = settings.otp_pepper.get_secret_value()

    # ------------------------------------------------------------------ helpers

    def _hash(self, *parts: str) -> str:
        return keyed_hash(self._pepper, *parts)

    def _code_hash(self, purpose: ChallengePurpose, email: str, code: str) -> str:
        return self._hash("otp", purpose.value, email, code)

    def _login_url(self) -> str:
        return self.s.frontend_base_url.rstrip("/") + "/login"

    async def check_password_policy(
        self, password: str, *, email: str | None, names: tuple[str | None, ...], field_name: str
    ) -> None:
        problem = self.policy.problems(password, email=email, names=names)
        if problem is None and await self.breach.is_breached(password):
            problem = "This password has appeared in a data breach. Choose a different one"
        if problem:
            raise ValidationFailed(fields={field_name: problem})

    async def _limit(self, key: str, limit: int, window_s: int) -> None:
        """Count this request; refuse once the window's limit is exceeded."""
        if await self.limiter.increment(key, window_s) > limit:
            raise TooManyAttempts()

    async def _send_quota_ok(self, purpose: ChallengePurpose, email: str) -> bool:
        """Per-address email cap. Over the cap we stay silent (same response) — AUTH-4."""
        count = await self.limiter.increment(f"send:{purpose.value}:{email}", 3600)
        return count <= self.s.otp_max_sends_per_hour

    async def _open_challenge(
        self,
        *,
        purpose: ChallengePurpose,
        email: str,
        user_id: uuid.UUID | None = None,
        pending_id: uuid.UUID | None = None,
    ) -> str:
        """Supersede any open challenge and create a new one. Returns the plaintext code,
        which exists only in memory long enough to be emailed."""
        now = self.clock.now()
        await repo.close_open_challenges(
            self.db, purpose=purpose, email=email, now=now, reason="superseded"
        )
        await self.db.flush()
        code = generate_otp(self.s.otp_length)
        self.db.add(
            AuthChallenge(
                purpose=purpose,
                email=email,
                user_id=user_id,
                pending_registration_id=pending_id,
                code_hash=self._code_hash(purpose, email, code),
                attempts=0,
                max_attempts=self.s.otp_max_attempts,
                expires_at=now + timedelta(minutes=self.s.otp_ttl_minutes),
                created_at=now,
                last_sent_at=now,
                send_count=1,
            )
        )
        return code

    async def _in_cooldown(self, purpose: ChallengePurpose, email: str) -> bool:
        await repo.lock_challenge_slot(self.db, purpose=purpose, email=email)
        existing = await repo.get_open_challenge(self.db, purpose=purpose, email=email)
        if existing is None:
            return False
        elapsed = self.clock.now() - existing.last_sent_at
        return elapsed < timedelta(seconds=self.s.otp_resend_cooldown_seconds)

    async def _check_code(
        self, purpose: ChallengePurpose, email: str, code: str, ctx: RequestContext
    ) -> AuthChallenge:
        """Validate an OTP against the open challenge (row-locked). Commits failed attempts."""
        await self._limit(
            f"otp-ip:{ctx.ip}",
            self.s.otp_verify_limit_per_ip,
            self.s.otp_verify_window_minutes * 60,
        )
        now = self.clock.now()
        challenge = await repo.get_open_challenge(
            self.db, purpose=purpose, email=email, for_update=True
        )
        if challenge is None or challenge.otp_verified_at is not None:
            raise BadRequest(INVALID_CODE_MESSAGE, code="invalid_code")
        if challenge.expires_at <= now:
            challenge.closed_at, challenge.close_reason = now, "expired"
            await self.db.commit()
            raise BadRequest(INVALID_CODE_MESSAGE, code="invalid_code")
        if not constant_time_equals(challenge.code_hash, self._code_hash(purpose, email, code)):
            challenge.attempts += 1
            if challenge.attempts >= challenge.max_attempts:
                challenge.closed_at, challenge.close_reason = now, "exhausted"
            await self.db.commit()
            raise BadRequest(INVALID_CODE_MESSAGE, code="invalid_code")
        return challenge

    # ------------------------------------------------------------------ registration

    async def register(
        self, *, first_name: str, last_name: str, email: str, password: str, ctx: RequestContext
    ) -> str:
        await self._limit(f"register-ip:{ctx.ip}", self.s.register_limit_per_ip_per_hour, 3600)
        await self.check_password_policy(
            password, email=email, names=(first_name, last_name), field_name="password"
        )
        # Hash before the existence check: both paths cost one Argon2 hash.
        password_hash = hash_password(password)
        now = self.clock.now()
        existing = await users_repo.get_by_email(self.db, email)
        if existing is not None:
            if await self._send_quota_ok(ChallengePurpose.EMAIL_VERIFICATION, email):
                subject, body = render("account_exists", login_url=self._login_url())
                self.outbox.add(OutgoingEmail(email, subject, body, "account_exists"))
            audit.record(
                self.db, action="auth.register_existing", now=now, target_id=existing.id, ip=ctx.ip
            )
            await self.db.commit()
            return GENERIC_REGISTER_MESSAGE

        pending_id = await repo.upsert_pending(
            self.db,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password_hash=password_hash,
            now=now,
            expires_at=now + timedelta(hours=self.s.pending_registration_hours),
        )
        if await self._in_cooldown(ChallengePurpose.EMAIL_VERIFICATION, email):
            await self.db.commit()  # details updated; the code already sent stays valid
            return GENERIC_REGISTER_MESSAGE
        if not await self._send_quota_ok(ChallengePurpose.EMAIL_VERIFICATION, email):
            await self.db.commit()
            return GENERIC_REGISTER_MESSAGE
        code = await self._open_challenge(
            purpose=ChallengePurpose.EMAIL_VERIFICATION, email=email, pending_id=pending_id
        )
        await self.db.commit()
        self._queue_verification(email, first_name, code)
        return GENERIC_REGISTER_MESSAGE

    def _queue_verification(self, email: str, name: str, code: str) -> None:
        subject, body = render(
            "verify_email", name=name, code=code, minutes=str(self.s.otp_ttl_minutes)
        )
        self.outbox.add(OutgoingEmail(email, subject, body, "verify_email"))

    async def resend_verification(self, *, email: str, ctx: RequestContext) -> str:
        await self._limit(f"register-ip:{ctx.ip}", self.s.register_limit_per_ip_per_hour, 3600)
        pending = await repo.get_pending_by_email(self.db, email)
        now = self.clock.now()
        if pending is None or pending.expires_at <= now:
            return GENERIC_RESEND_MESSAGE
        if await self._in_cooldown(ChallengePurpose.EMAIL_VERIFICATION, email):
            return GENERIC_RESEND_MESSAGE
        if not await self._send_quota_ok(ChallengePurpose.EMAIL_VERIFICATION, email):
            return GENERIC_RESEND_MESSAGE
        code = await self._open_challenge(
            purpose=ChallengePurpose.EMAIL_VERIFICATION, email=email, pending_id=pending.id
        )
        await self.db.commit()
        self._queue_verification(email, pending.first_name, code)
        return GENERIC_RESEND_MESSAGE

    async def verify_email(self, *, email: str, code: str, ctx: RequestContext) -> User:
        challenge = await self._check_code(ChallengePurpose.EMAIL_VERIFICATION, email, code, ctx)
        now = self.clock.now()
        pending = (
            await repo.get_pending(self.db, challenge.pending_registration_id, for_update=True)
            if challenge.pending_registration_id
            else None
        )
        if pending is None or pending.expires_at <= now:
            challenge.closed_at, challenge.close_reason = now, "expired"
            await self.db.commit()
            raise BadRequest(INVALID_CODE_MESSAGE, code="invalid_code")

        challenge.closed_at, challenge.close_reason = now, "consumed"
        user = User(
            email=email,
            first_name=pending.first_name,
            last_name=pending.last_name,
            role=Role.USER,  # public registration can never create an admin
            password_hash=pending.password_hash,
            email_verified_at=now,
            is_active=True,
            token_version=0,
            source=UserSource.REGISTRATION,
        )
        users_repo.add(self.db, user)
        try:
            await self.db.flush()
        except IntegrityError:
            # Someone (e.g. an admin) created this email meanwhile. The caller has proved
            # control of the address, so telling them is not an enumeration leak.
            await self.db.rollback()
            raise Conflict(
                "An account already exists for this email. Sign in or reset your password",
                code="account_exists",
            ) from None
        await repo.delete_pending(self.db, pending.id)
        audit.record(self.db, action="auth.registered", now=now, target_id=user.id, ip=ctx.ip)
        await self.db.commit()
        subject, body = render(
            "account_activated",
            name=user.first_name or "",
            email=email,
            login_url=self._login_url(),
        )
        self.outbox.add(OutgoingEmail(email, subject, body, "account_activated"))
        return user

    # ------------------------------------------------------------------ login & sessions

    def _ip_key(self, ctx: RequestContext) -> str:
        return f"login-ip:{ctx.ip}"

    async def login(
        self,
        *,
        email: str,
        password: str,
        remember: bool,
        admin_mode: bool,
        ctx: RequestContext,
    ) -> IssuedSession:
        window = self.s.login_window_minutes * 60
        email_key = f"login-email:{email}"
        if (
            await self.limiter.count(email_key) >= self.s.login_fail_limit_per_email
            or await self.limiter.count(self._ip_key(ctx)) >= self.s.login_fail_limit_per_ip
        ):
            raise TooManyAttempts()

        now = self.clock.now()
        user = await users_repo.get_by_email(self.db, email)
        password_ok = verify_password(user.password_hash if user else None, password)
        eligible = (
            user is not None
            and password_ok
            and user.is_active
            and user.email_verified_at is not None
            and (not admin_mode or user.role is Role.ADMIN)
        )
        if not eligible or user is None:
            await self.limiter.increment(email_key, window)
            await self.limiter.increment(self._ip_key(ctx), window)
            audit.record(
                self.db,
                action="auth.login_failed",
                now=now,
                target_id=user.id if user else None,
                ip=ctx.ip,
                details={"mode": "admin" if admin_mode else "user"},
            )
            await self.db.commit()
            raise InvalidCredentials()

        await self.limiter.reset(email_key)
        if user.password_hash and password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = now
        issued = self._new_session(user, remember=remember, ctx=ctx)
        audit.record(
            self.db,
            action="auth.login",
            now=now,
            actor_id=user.id,
            target_id=user.id,
            ip=ctx.ip,
            details={"mode": "admin" if admin_mode else "user", "remember": remember},
        )
        await self.db.commit()
        return issued

    def _session_ttl(self, remember: bool) -> timedelta:
        if remember:
            return timedelta(days=self.s.session_days_remember)
        return timedelta(hours=self.s.session_hours_default)

    def _access(self, user: User, session: AuthSession) -> tuple[str, datetime]:
        now = self.clock.now()
        ttl = timedelta(minutes=self.s.access_token_minutes)
        # Never outlive the session itself.
        ttl = min(ttl, session.expires_at - now)
        return self.codec.encode(
            user_id=user.id,
            session_id=session.id,
            token_version=user.token_version,
            now=now,
            ttl=ttl,
        )

    def _new_session(self, user: User, *, remember: bool, ctx: RequestContext) -> IssuedSession:
        now = self.clock.now()
        refresh = generate_opaque_token()
        session = AuthSession(
            id=uuid.uuid4(),
            user_id=user.id,
            refresh_token_hash=self._hash("refresh", refresh),
            token_version=user.token_version,
            remember=remember,
            created_at=now,
            last_used_at=now,
            expires_at=now + self._session_ttl(remember),
            user_agent=(ctx.user_agent or "")[:255] or None,
            ip_address=ctx.ip,
        )
        self.db.add(session)
        token, exp = self._access(user, session)
        return IssuedSession(token, exp, refresh, session.expires_at, remember, user)

    async def refresh(self, *, refresh_token: str, ctx: RequestContext) -> IssuedSession:
        now = self.clock.now()
        token_hash = self._hash("refresh", refresh_token)
        session = await repo.get_session_by_refresh_hash(self.db, token_hash)
        grace = False
        if session is None:
            session = await repo.get_session_by_previous_hash(self.db, token_hash)
            if session is None:
                raise Unauthorized()
            if session.revoked_at is None and now - session.last_used_at <= REFRESH_REUSE_GRACE:
                # Two tabs refreshed at once: the cookie jar already holds the rotated token.
                grace = True
            else:
                # A rotated-out token came back later: likely stolen. Kill the session.
                session.revoked_at, session.revoke_reason = now, "refresh_reuse"
                audit.record(
                    self.db,
                    action="auth.refresh_reuse",
                    now=now,
                    target_id=session.user_id,
                    ip=ctx.ip,
                )
                await self.db.commit()
                raise Unauthorized()

        user = await users_repo.get_by_id(self.db, session.user_id)
        if (
            session.revoked_at is not None
            or session.expires_at <= now
            or user is None
            or not user.is_active
            or user.token_version != session.token_version
        ):
            raise Unauthorized()

        if grace:
            token, exp = self._access(user, session)
            return IssuedSession(token, exp, None, session.expires_at, session.remember, user)

        new_refresh = generate_opaque_token()
        session.previous_refresh_token_hash = session.refresh_token_hash
        session.refresh_token_hash = self._hash("refresh", new_refresh)
        session.last_used_at = now
        token, exp = self._access(user, session)
        await self.db.commit()
        return IssuedSession(token, exp, new_refresh, session.expires_at, session.remember, user)

    async def logout(
        self, *, session_id: uuid.UUID | None, refresh_token: str | None, ctx: RequestContext
    ) -> None:
        now = self.clock.now()
        session: AuthSession | None = None
        if session_id is not None:
            session = await repo.get_session(self.db, session_id)
        if session is None and refresh_token:
            session = await repo.get_session_by_refresh_hash(
                self.db, self._hash("refresh", refresh_token)
            )
        if session is None or session.revoked_at is not None:
            return
        session.revoked_at, session.revoke_reason = now, "logout"
        audit.record(
            self.db,
            action="auth.logout",
            now=now,
            actor_id=session.user_id,
            target_id=session.user_id,
            ip=ctx.ip,
        )
        await self.db.commit()

    async def authenticate_access_token(self, token: str) -> tuple[User, uuid.UUID]:
        """Resolve a bearer token to (user, session_id). Role/active come from the DB."""
        from netribeat.auth.security import TokenError

        now = self.clock.now()
        try:
            claims = self.codec.decode(token, now=now)
        except TokenError:
            raise Unauthorized() from None
        user = await users_repo.get_by_id(self.db, claims.user_id)
        if user is None or not user.is_active or user.token_version != claims.token_version:
            raise Unauthorized()
        session = await repo.get_session(self.db, claims.session_id)
        if (
            session is None
            or session.user_id != user.id
            or session.revoked_at is not None
            or session.expires_at <= now
            or session.token_version != user.token_version
        ):
            raise Unauthorized()
        return user, session.id

    # ------------------------------------------------------------------ device sessions

    async def list_sessions(self, user_id: uuid.UUID) -> list[AuthSession]:
        return await repo.list_active_sessions(self.db, user_id, now=self.clock.now())

    async def revoke_session(
        self, *, owner: User, session_id: uuid.UUID, ctx: RequestContext
    ) -> None:
        """Revoke one of the owner's own sessions. Someone else's session id is a 404, so
        ids can't be probed."""
        now = self.clock.now()
        session = await repo.get_session(self.db, session_id)
        if session is None or session.user_id != owner.id or session.revoked_at is not None:
            raise NotFound("Session not found")
        session.revoked_at, session.revoke_reason = now, "revoked_by_user"
        audit.record(
            self.db,
            action="user.session_revoked",
            now=now,
            actor_id=owner.id,
            target_id=owner.id,
            ip=ctx.ip,
            details={"session_id": str(session_id)},
        )
        await self.db.commit()

    async def revoke_other_sessions(
        self, *, owner: User, current_session: uuid.UUID, ctx: RequestContext
    ) -> None:
        now = self.clock.now()
        await repo.revoke_all_sessions(
            self.db, owner.id, now=now, reason="revoked_by_user", except_session=current_session
        )
        audit.record(
            self.db,
            action="user.other_sessions_revoked",
            now=now,
            actor_id=owner.id,
            target_id=owner.id,
            ip=ctx.ip,
        )
        await self.db.commit()

    async def admin_revoke_all(
        self, *, actor: User, target_id: uuid.UUID, ctx: RequestContext
    ) -> None:
        """Admin "sign out everywhere" for any user (e.g. a suspected compromise)."""
        if actor.role is not Role.ADMIN:
            raise Forbidden()
        target = await users_repo.get_by_id(self.db, target_id, for_update=True)
        if target is None:
            raise NotFound("User not found")
        now = self.clock.now()
        target.token_version += 1
        await repo.revoke_all_sessions(self.db, target.id, now=now, reason="revoked_by_admin")
        audit.record(
            self.db,
            action="admin.sessions_revoked",
            now=now,
            actor_id=actor.id,
            target_id=target.id,
            ip=ctx.ip,
        )
        await self.db.commit()

    # ------------------------------------------------------------------ password reset

    async def forgot_password(self, *, email: str, ctx: RequestContext) -> str:
        await self._limit(f"forgot-ip:{ctx.ip}", self.s.forgot_limit_per_ip_per_hour, 3600)
        user = await users_repo.get_by_email(self.db, email)
        if user is None or not user.is_active:
            return GENERIC_FORGOT_MESSAGE
        if await self._in_cooldown(ChallengePurpose.PASSWORD_RESET, email):
            return GENERIC_FORGOT_MESSAGE
        if not await self._send_quota_ok(ChallengePurpose.PASSWORD_RESET, email):
            return GENERIC_FORGOT_MESSAGE
        code = await self._open_challenge(
            purpose=ChallengePurpose.PASSWORD_RESET, email=email, user_id=user.id
        )
        audit.record(
            self.db,
            action="auth.reset_requested",
            now=self.clock.now(),
            target_id=user.id,
            ip=ctx.ip,
        )
        await self.db.commit()
        subject, body = render(
            "password_reset_code",
            name=user.first_name or "there",
            email=email,
            code=code,
            minutes=str(self.s.otp_ttl_minutes),
        )
        self.outbox.add(OutgoingEmail(email, subject, body, "password_reset_code"))
        return GENERIC_FORGOT_MESSAGE

    async def verify_reset_otp(
        self, *, email: str, code: str, ctx: RequestContext
    ) -> ResetAuthorisation:
        challenge = await self._check_code(ChallengePurpose.PASSWORD_RESET, email, code, ctx)
        now = self.clock.now()
        reset_token = generate_opaque_token()
        challenge.otp_verified_at = now
        challenge.reset_token_hash = self._hash("reset", reset_token)
        challenge.reset_token_expires_at = now + timedelta(minutes=self.s.reset_token_ttl_minutes)
        await self.db.commit()
        return ResetAuthorisation(reset_token, challenge.reset_token_expires_at)

    async def reset_password(self, *, reset_token: str, password: str, ctx: RequestContext) -> None:
        now = self.clock.now()
        challenge = await repo.get_challenge_by_reset_hash(
            self.db, self._hash("reset", reset_token)
        )
        invalid = BadRequest(
            'This reset link or code has expired. Start again from "Forgot password?"',
            code="invalid_reset_token",
        )
        if (
            challenge is None
            or challenge.purpose is not ChallengePurpose.PASSWORD_RESET
            or challenge.reset_token_expires_at is None
            or challenge.reset_token_expires_at <= now
            or challenge.user_id is None
        ):
            raise invalid
        user = await users_repo.get_by_id(self.db, challenge.user_id, for_update=True)
        if user is None or not user.is_active or user.email != challenge.email:
            raise invalid
        await self.check_password_policy(
            password,
            email=user.email,
            names=(user.first_name, user.last_name),
            field_name="password",
        )
        user.password_hash = hash_password(password)
        # Proving control of the inbox verifies the address (admin/import-created users).
        user.email_verified_at = user.email_verified_at or now
        user.token_version += 1
        await repo.revoke_all_sessions(self.db, user.id, now=now, reason="password_reset")
        challenge.closed_at, challenge.close_reason = now, "consumed"
        audit.record(
            self.db,
            action="auth.password_reset",
            now=now,
            actor_id=user.id,
            target_id=user.id,
            ip=ctx.ip,
        )
        await self.db.commit()
        subject, body = render(
            "password_reset_done",
            name=user.first_name or "there",
            email=user.email or "",
            when=now.strftime("%Y-%m-%d %H:%M"),
            login_url=self._login_url(),
        )
        self.outbox.add(OutgoingEmail(user.email or "", subject, body, "password_reset_done"))

    # ------------------------------------------------------------------ signed-in actions

    async def change_password(
        self,
        *,
        user: User,
        session_id: uuid.UUID,
        current_password: str,
        new_password: str,
        ctx: RequestContext,
    ) -> None:
        now = self.clock.now()
        if not verify_password(user.password_hash, current_password):
            raise ValidationFailed(fields={"currentPassword": "Current password is incorrect"})
        if verify_password(user.password_hash, new_password):
            raise ValidationFailed(
                fields={"newPassword": "Choose a password you haven't used here"}
            )
        await self.check_password_policy(
            new_password,
            email=user.email,
            names=(user.first_name, user.last_name),
            field_name="newPassword",
        )
        user.password_hash = hash_password(new_password)
        # Sign out every other device; this one stays signed in.
        await repo.revoke_all_sessions(
            self.db, user.id, now=now, reason="password_changed", except_session=session_id
        )
        audit.record(
            self.db,
            action="user.password_changed",
            now=now,
            actor_id=user.id,
            target_id=user.id,
            ip=ctx.ip,
        )
        await self.db.commit()
        if user.email:
            subject, body = render(
                "password_reset_done",
                name=user.first_name or "there",
                email=user.email,
                when=now.strftime("%Y-%m-%d %H:%M"),
                login_url=self._login_url(),
            )
            self.outbox.add(OutgoingEmail(user.email, subject, body, "password_changed"))


async def cleanup_expired(db: AsyncSession, now: datetime) -> dict[str, int]:
    """Expire challenges; drop old pending sign-ups, closed challenges and dead sessions."""
    result = {
        "challenges_expired": await repo.close_expired_challenges(db, now),
        "pending_deleted": await repo.delete_expired_pending(db, now),
        "challenges_deleted": await repo.delete_closed_challenges_before(
            db, now - timedelta(days=7)
        ),
        "sessions_deleted": await repo.delete_dead_sessions(db, now - timedelta(days=7)),
    }
    await db.commit()
    return result


async def revoke_user_sessions(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime, reason: str
) -> None:
    """Public interface for other features (users admin): sign a user out everywhere."""
    await repo.revoke_all_sessions(db, user_id, now=now, reason=reason)
