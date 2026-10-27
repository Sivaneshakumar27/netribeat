"""Request/response schemas for /auth, /users/me and /admin (messages match the UI)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from netribeat.auth.models import Gender, Role, UserSource
from netribeat.core.api_model import ApiModel
from netribeat.email.validation import validated_email

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
    gender: str | None = None
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


# ---------------------------------------------------------------- profile and admin


class ProfileUpdate(ApiModel):
    first_name: Name | None = None
    last_name: Name | None = None
    age: Annotated[int, Field(ge=8, le=100)] | None = None
    gender: Gender | None = None
    height_cm: Annotated[int, Field(ge=80, le=250)] | None = None
    weight_kg: Annotated[float, Field(ge=20, le=300)] | None = None
    hr_rest: Annotated[int, Field(ge=25, le=120)] | None = None


class ChangePasswordRequest(ApiModel):
    current_password: Password
    new_password: Password
    confirm_password: Password


class AdminUserOut(UserOut):
    source: UserSource
    token_version: int
    updated_at: datetime


class AdminUserList(ApiModel):
    items: list[AdminUserOut]
    total: int
    limit: int
    offset: int


class AdminCreateUser(ApiModel):
    email: Email
    first_name: Name
    last_name: Name
    age: Annotated[int, Field(ge=8, le=100)] | None = None
    send_invite: bool = True


class AdminSetActive(ApiModel):
    is_active: bool


class AdminSetRole(ApiModel):
    role: Role


class AuditEventOut(ApiModel):
    id: uuid.UUID
    created_at: datetime
    action: str
    actor_user_id: uuid.UUID | None
    target_user_id: uuid.UUID | None
    ip_address: str | None
    details: dict[str, object]


class AuditEventList(ApiModel):
    items: list[AuditEventOut]
    total: int
    limit: int
    offset: int
