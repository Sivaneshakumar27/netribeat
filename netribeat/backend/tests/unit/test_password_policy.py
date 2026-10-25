from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from netribeat.auth.password_policy import COMMON_PASSWORDS, PasswordPolicy

POLICY = PasswordPolicy(min_length=12, max_length=128)


def test_accepts_long_passphrase() -> None:
    assert POLICY.problems("correct horse battery staple") is None


def test_rejects_short_password() -> None:
    assert POLICY.problems("short1!") == "Use at least 12 characters"


def test_rejects_too_long_password() -> None:
    assert POLICY.problems("a1b2c3d4" * 20) == "Use at most 128 characters"


def test_rejects_common_password_case_insensitively() -> None:
    assert "password1234" in COMMON_PASSWORDS
    assert POLICY.problems("PassWord1234") is not None


def test_rejects_low_variety() -> None:
    assert POLICY.problems("aaaaaaaaaaaaaaab") == "Use a password with more variety"


def test_rejects_email_local_part() -> None:
    msg = POLICY.problems("priya.raman-2026!", email="priya.raman@example.org")
    assert msg == "Don't include your email address in your password"


def test_rejects_own_name() -> None:
    msg = POLICY.problems("ilovegeraldine99", names=("Geraldine", "Smith"))
    assert msg == "Don't include your name in your password"


def test_minimum_policy_of_eight_is_allowed() -> None:
    assert PasswordPolicy(8, 128).problems("kq7#vz2p") is None


@given(st.text(max_size=11))
def test_any_password_under_min_length_is_rejected(pw: str) -> None:
    assert POLICY.problems(pw) is not None
