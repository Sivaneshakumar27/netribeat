"""Schemas for the current user's profile and admin user management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints

from netribeat.api_model import ApiModel
from netribeat.auth.schemas import Email, Password, UserOut
from netribeat.users.models import Role, Sex, UserSource

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ProfileUpdate(ApiModel):
    first_name: Name | None = None
    last_name: Name | None = None
    age: Annotated[int, Field(ge=8, le=100)] | None = None
    sex: Sex | None = None
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
