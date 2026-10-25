"""Recording sessions, their source files and stored analysis results."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, Enum, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from netribeat.db import Base


def _enum(cls: type[StrEnum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class SessionType(StrEnum):
    REST = "rest"
    TRAINING = "training"
    MATCH = "match"
    RECOVERY = "recovery"
    TEST = "test"


class Device(StrEnum):
    CHEST_STRAP_RR_ACC = "chest_strap_rr_acc"
    CHEST_STRAP_RR = "chest_strap_rr"
    ECG_HOLTER = "ecg_holter"
    OPTICAL_WRIST = "optical_wrist"
    OTHER = "other"


class SessionStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ValueSource(StrEnum):
    FORM = "form"  # entered at upload
    FILE = "file"  # read from the file's metadata
    UPLOAD_TIME = "upload_time"  # recording time unknown: time of upload
    UNKNOWN = "unknown"


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_recorded", "user_id", "recorded_at"),
        Index("ix_sessions_status", "status"),
        Index("ix_sessions_recorded_at", "recorded_at"),
        CheckConstraint("age IS NULL OR age BETWEEN 8 AND 100", name="age_range"),
        CheckConstraint(
            "hr_max_manual IS NULL OR hr_max_manual BETWEEN 100 AND 230", name="hr_max_range"
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Ownership: always set by the server from the authenticated actor (or an admin's
    # explicit choice), never from a client-supplied owner field.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    type: Mapped[SessionType] = mapped_column(_enum(SessionType, "session_type"))
    device: Mapped[Device] = mapped_column(_enum(Device, "device"))
    recorded_at: Mapped[datetime]
    recorded_at_source: Mapped[ValueSource] = mapped_column(_enum(ValueSource, "value_source"))
    age: Mapped[int | None]
    age_source: Mapped[ValueSource] = mapped_column(
        _enum(ValueSource, "value_source"), default=ValueSource.UNKNOWN
    )
    hr_max_manual: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(String(500))
    file_name: Mapped[str] = mapped_column(String(255))

    status: Mapped[SessionStatus] = mapped_column(
        _enum(SessionStatus, "session_status"), default=SessionStatus.PROCESSING
    )
    error: Mapped[str | None] = mapped_column(String(500))  # user-safe message only
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime | None]

    # Summary columns (copied from the analysis for fast lists and stats)
    quality: Mapped[str | None] = mapped_column(String(16))
    reliable: Mapped[bool | None]
    duration_s: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    rmssd: Mapped[float | None] = mapped_column(Float)
    training_load: Mapped[float | None] = mapped_column(Float)
    artefact_count: Mapped[int | None]
    artefact_pct: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class SessionFile(Base):
    __tablename__ = "session_files"
    __table_args__ = (Index("ix_session_files_session_id", "session_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))  # original file name: display only
    kind: Mapped[str | None] = mapped_column(String(8))  # ecg | rr (after parsing)
    format: Mapped[str | None] = mapped_column(String(40))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)  # opaque
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AnalysisResult(Base):
    """Derived results. Bounded in size (metrics + 1 Hz HR + RR series + 10 s ECG strip),
    kept in JSONB so they commit atomically with the session status. Raw signals stay in
    file storage."""

    __tablename__ = "analysis_results"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    analysis_version: Mapped[str] = mapped_column(String(20))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
