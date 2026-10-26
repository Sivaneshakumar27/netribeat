"""User ORM model. Every person in the system is a user (no separate athlete profile)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Enum, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from netribeat.db import Base


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"


class HrMaxMethod(StrEnum):
    AGE = "age"
    PEAK = "peak"
    MANUAL = "manual"


class Gender(StrEnum):
    FEMALE = "female"
    MALE = "male"
    OTHER = "other"


class UserSource(StrEnum):
    REGISTRATION = "registration"  # public sign-up with email OTP
    ADMIN = "admin"  # created by an admin (CLI or admin API)
    IMPORT = "import"  # created by a dataset import (e.g. a D-folder individual)
    UPLOAD = "upload"  # created when an admin uploads for a new email


def _enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email IS NULL OR email = lower(btrim(email))", name="email_normalised"),
        CheckConstraint("age IS NULL OR age BETWEEN 8 AND 100", name="age_range"),
        CheckConstraint(
            "hr_max_manual IS NULL OR hr_max_manual BETWEEN 100 AND 230", name="hr_max_manual_range"
        ),
        CheckConstraint(
            "hr_max_method IS NULL OR hr_max_method <> 'manual' OR hr_max_manual IS NOT NULL",
            name="hr_max_manual_required",
        ),
        CheckConstraint("token_version >= 0", name="token_version_nonneg"),
        CheckConstraint("height_cm IS NULL OR height_cm BETWEEN 80 AND 250", name="height_range"),
        CheckConstraint("weight_kg IS NULL OR weight_kg BETWEEN 20 AND 300", name="weight_range"),
        CheckConstraint("hr_rest IS NULL OR hr_rest BETWEEN 25 AND 120", name="hr_rest_range"),
        Index("ix_users_role", "role"),
        Index("ix_users_created_at", "created_at"),
        Index("ix_users_last_name_first_name", "last_name", "first_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Nullable: an imported individual (e.g. "D1") has no email until an admin assigns one.
    # PostgreSQL unique constraints allow many NULLs, so uniqueness applies to real emails only.
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[Role] = mapped_column(
        _enum(Role, "user_role"), default=Role.USER, server_default=Role.USER.value
    )
    # Null until the person establishes a password (admin-, import- or upload-created users
    # get one through the forgot-password flow, which proves control of the email).
    password_hash: Mapped[str | None] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None]
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    source: Mapped[UserSource] = mapped_column(
        _enum(UserSource, "user_source"), default=UserSource.REGISTRATION
    )
    # Analysis settings (design-spec §6 Max HR)
    age: Mapped[int | None]
    hr_max_method: Mapped[HrMaxMethod | None] = mapped_column(_enum(HrMaxMethod, "hr_max_method"))
    hr_max_manual: Mapped[int | None]
    # Subject details shown in the HRV report header (all optional)
    gender: Mapped[Gender | None] = mapped_column(_enum(Gender, "gender"))
    height_cm: Mapped[int | None]
    weight_kg: Mapped[float | None]
    hr_rest: Mapped[int | None]

    last_login_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    @property
    def display_name(self) -> str:
        name = " ".join(p for p in (self.first_name, self.last_name) if p)
        return name or "NetriBeat user"
