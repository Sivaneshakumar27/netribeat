from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from netribeat.auth.security import (
    TokenCodec,
    TokenError,
    generate_opaque_token,
    generate_otp,
    hash_password,
    keyed_hash,
    verify_password,
)

NOW = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
SECRET = "s" * 48
NO_TIME = {"verify_exp": False, "verify_iat": False}


def test_hash_password_is_argon2id_and_salted() -> None:
    a, b = hash_password("same password here"), hash_password("same password here")
    assert a.startswith("$argon2id$")
    assert a != b  # random salt


def test_verify_password_round_trip_and_wrong_password() -> None:
    h = hash_password("right horse battery")
    assert verify_password(h, "right horse battery")
    assert not verify_password(h, "wrong horse battery")


def test_verify_password_without_hash_is_false() -> None:
    assert verify_password(None, "anything at all") is False


def test_verify_password_with_garbage_hash_is_false() -> None:
    assert verify_password("not-a-hash", "anything") is False


def test_otp_is_numeric_with_requested_length() -> None:
    codes = {generate_otp(6) for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 150  # random, not constant


def test_opaque_token_has_256_bits() -> None:
    assert len(generate_opaque_token()) >= 43


def test_keyed_hash_binds_every_part() -> None:
    base = keyed_hash("pepper", "otp", "email_verification", "a@x.org", "123456")
    assert base != keyed_hash("pepper", "otp", "password_reset", "a@x.org", "123456")
    assert base != keyed_hash("pepper", "otp", "email_verification", "b@x.org", "123456")
    assert base != keyed_hash("other", "otp", "email_verification", "a@x.org", "123456")
    assert "123456" not in base


def _encode(codec: TokenCodec, **kw: object) -> str:
    token, _ = codec.encode(
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        token_version=3,
        now=NOW,
        ttl=timedelta(minutes=15),
        **kw,  # type: ignore[arg-type]
    )
    return token


def test_token_round_trip() -> None:
    codec = TokenCodec(SECRET)
    uid, sid = uuid.uuid4(), uuid.uuid4()
    token, exp = codec.encode(
        user_id=uid, session_id=sid, token_version=7, now=NOW, ttl=timedelta(minutes=15)
    )
    claims = codec.decode(token, now=NOW + timedelta(minutes=1))
    assert (claims.user_id, claims.session_id, claims.token_version) == (uid, sid, 7)
    assert exp == NOW + timedelta(minutes=15)


def test_token_has_no_role_claim() -> None:
    payload = jwt.decode(_encode(TokenCodec(SECRET)), SECRET, algorithms=["HS256"], options=NO_TIME)
    assert "role" not in payload


def test_token_expired_is_rejected() -> None:
    codec = TokenCodec(SECRET)
    token = _encode(codec)
    with pytest.raises(TokenError):
        codec.decode(token, now=NOW + timedelta(minutes=15))


def test_token_signed_with_other_secret_is_rejected() -> None:
    token = _encode(TokenCodec("x" * 48))
    with pytest.raises(TokenError):
        TokenCodec(SECRET).decode(token, now=NOW)


def test_token_alg_none_is_rejected() -> None:
    payload = jwt.decode(_encode(TokenCodec(SECRET)), SECRET, algorithms=["HS256"], options=NO_TIME)
    forged = jwt.encode(payload, key="", algorithm="none")
    with pytest.raises(TokenError):
        TokenCodec(SECRET).decode(forged, now=NOW)


def test_token_tampered_payload_is_rejected() -> None:
    token = _encode(TokenCodec(SECRET))
    head, body, sig = token.split(".")
    tampered = f"{head}.{body[:-2]}AA.{sig}"
    with pytest.raises(TokenError):
        TokenCodec(SECRET).decode(tampered, now=NOW)


def test_token_wrong_type_is_rejected() -> None:
    payload = jwt.decode(_encode(TokenCodec(SECRET)), SECRET, algorithms=["HS256"], options=NO_TIME)
    payload["typ"] = "refresh"
    other = jwt.encode(payload, SECRET, algorithm="HS256")
    with pytest.raises(TokenError):
        TokenCodec(SECRET).decode(other, now=NOW)


def test_token_issued_in_the_future_is_rejected() -> None:
    codec = TokenCodec(SECRET)
    token = _encode(codec)
    with pytest.raises(TokenError):
        codec.decode(token, now=NOW - timedelta(minutes=5))
