"""Request/response schemas for /auth. Field-level messages match the UI copy."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from netribeat.api_model import ApiModel
from netribeat.core.emails import validated_email
from netribeat.users.models import Role

Email = Annotated[str, Field(max_length=320), AfterValidator(validated_email)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Policy (length, blocklist) is checked in the service so its message can use settings;
# here we only bound the size so a huge body can't reach Argon2.
Password = Annotated[str, Field(min_length=1, max_length=1024)]
OtpCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6,10}$")]


class LoginMode(StrEnum):
    USER = "user"
    ADMIN = "admin"


class RegisterRequest(ApiModel):
    first_name: Name
    last_name: Name
    email: Email
    password: Password
    confirm_password: Password
    # Public registration always creates role `user`. The field exists only so a client
    # that sends it gets a clear 400 instead of silently being ignored.
    role: Literal["user"] = "user"

    @model_validator(mode="after")
    def _passwords_match(self) -> RegisterRequest:
        if self.password != self.confirm_password:
            raise ValueError("confirm_password: Passwords don't match")
        return self


class VerifyEmailRequest(ApiModel):
    email: Email
    code: OtpCode


class EmailOnlyRequest(ApiModel):
    email: Email


class LoginRequest(ApiModel):
    email: Email
    password: Password
    remember: bool = False
    mode: LoginMode = LoginMode.USER


class VerifyResetOtpRequest(ApiModel):
    email: Email
    code: OtpCode


class ResetPasswordRequest(ApiModel):
    reset_token: Annotated[str, Field(min_length=20, max_length=200)]
    password: Password
    confirm_password: Password

    @model_validator(mode="after")
    def _passwords_match(self) -> ResetPasswordRequest:
        if self.password != self.confirm_password:
            raise ValueError("confirm_password: Passwords don't match")
        return self


class UserOut(ApiModel):
    """The signed-in account (`User` in the API spec, extended per BE-0.2)."""

    id: uuid.UUID
    email: str | None
    first_name: str | None
    last_name: str | None
    name: str
    role: Role
    email_verified: bool
    has_password: bool
    is_active: bool
    age: int | None
    sex: str | None = None
    height_cm: int | None = None
    weight_kg: float | None = None
    hr_rest: int | None = None
    created_at: datetime
    last_login_at: datetime | None


class LoginResponse(ApiModel):
    token: str
    expires_at: datetime
    user: UserOut


class AcceptedResponse(ApiModel):
    status: str
    message: str


class ResetTokenResponse(ApiModel):
    reset_token: str
    expires_at: datetime


class SessionOut(ApiModel):
    """A signed-in device. Tokens are never included."""

    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    remember: bool
    user_agent: str | None
    ip_address: str | None
    current: bool


class SessionList(ApiModel):
    items: list[SessionOut]
