"""Cryptographic primitives: password hashing, signed access tokens, OTPs and opaque tokens.

Pure functions plus small classes; no database, no FastAPI.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Argon2id with argon2-cffi's RFC 9106 "low memory" profile defaults
# (t=3, m=64 MiB, p=4). Tuned for interactive logins on a small server.
_hasher = PasswordHasher()

# A real hash of a random string, verified against when the account does not exist or has
# no password, so a failed login takes the same time either way (no user enumeration).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))

CLOCK_SKEW_SECONDS = 30
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 — a claim value, not a secret


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-work verification. A missing hash still costs one Argon2 verify."""
    target = password_hash if password_hash is not None else _DUMMY_HASH
    try:
        ok = _hasher.verify(target, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return ok and password_hash is not None


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


# ---------------------------------------------------------------- OTPs and opaque tokens


def generate_otp(length: int) -> str:
    """Uniformly random numeric code from the OS CSPRNG (leading zeros allowed)."""
    return "".join(secrets.choice("0123456789") for _ in range(length))


def generate_opaque_token() -> str:
    """256-bit URL-safe token for refresh sessions and password-reset authorisation."""
    return secrets.token_urlsafe(32)


def keyed_hash(pepper: str, *parts: str) -> str:
    """HMAC-SHA256 over the parts. Binding purpose and email into the MAC means a code
    issued for one purpose/address can never validate for another."""
    msg = "\x1f".join(parts).encode()
    return hmac.new(pepper.encode(), msg, hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ---------------------------------------------------------------- access tokens (JWT)


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    token_version: int
    expires_at: datetime


class TokenError(Exception):
    """Any problem with an access token. The caller maps it to a generic 401."""


class TokenCodec:
    def __init__(self, secret: str, algorithm: str = "HS256") -> None:
        self._secret = secret
        self._algorithm = algorithm

    def encode(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        token_version: int,
        now: datetime,
        ttl: timedelta,
    ) -> tuple[str, datetime]:
        expires_at = now + ttl
        payload = {
            "sub": str(user_id),
            "sid": str(session_id),
            "ver": token_version,
            "typ": ACCESS_TOKEN_TYPE,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": uuid.uuid4().hex,
        }
        token = jwt.encode(payload, self._secret, algorithm=self._algorithm)
        return token, expires_at

    def decode(self, token: str, *, now: datetime) -> AccessClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],  # pinned: rejects alg=none and alg confusion
                options={
                    "require": ["sub", "sid", "ver", "exp", "iat", "typ"],
                    # Time claims are checked below against the injected clock.
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise TokenError("invalid token") from exc
        # Expiry is checked against the injected clock so tests can freeze time.
        try:
            exp, iat = int(payload["exp"]), int(payload["iat"])
        except (TypeError, ValueError) as exc:
            raise TokenError("malformed time claims") from exc
        now_ts = int(now.timestamp())
        if exp <= now_ts:
            raise TokenError("expired")
        if iat > now_ts + CLOCK_SKEW_SECONDS:
            raise TokenError("issued in the future")
        if payload.get("typ") != ACCESS_TOKEN_TYPE:
            raise TokenError("wrong token type")
        try:
            return AccessClaims(
                user_id=uuid.UUID(str(payload["sub"])),
                session_id=uuid.UUID(str(payload["sid"])),
                token_version=int(payload["ver"]),
                expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=now.tzinfo),
            )
        except (ValueError, TypeError) as exc:
            raise TokenError("malformed claims") from exc
