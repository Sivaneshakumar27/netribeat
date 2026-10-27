"""One row per analysed session. The uploaded hex file is kept in the row (no disk storage)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from netribeat.db import Base


class Recording(Base):
    """A session decoded from a hex file. One file can hold several sessions (`part`)."""

    __tablename__ = "recordings"
    __table_args__ = (
        Index("ix_recordings_user_id", "user_id"),
        Index("ix_recordings_recorded_at", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    # Upload form
    type: Mapped[str] = mapped_column(String(20))  # training | rest | match | recovery | test
    device: Mapped[str] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(String(500))
    # Subject details entered on upload (optional; empty -> the owner's profile value)
    athlete_name: Mapped[str | None] = mapped_column(String(100))  # empty -> from the file name
    age: Mapped[int | None]
    age_source: Mapped[str] = mapped_column(String(10))  # entered | profile | none
    gender: Mapped[str | None] = mapped_column(String(10))  # male | female | other
    resting_hr: Mapped[int | None]
    height_cm: Mapped[int | None]
    weight_kg: Mapped[float | None] = mapped_column(Float)
    hr_max_manual: Mapped[int | None]  # per-upload override
    recorded_at: Mapped[datetime]
    recorded_at_source: Mapped[str] = mapped_column(String(10))  # file | entered | upload

    # The original file
    file_name: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int]
    file_data: Mapped[bytes] = deferred(mapped_column(LargeBinary))
    part: Mapped[int] = mapped_column(Integer, default=0)  # session index inside the file

    # Processing
    status: Mapped[str] = mapped_column(String(12), default="processing")  # ready | failed
    error: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime | None]

    # Results (summary columns for lists; everything in metrics / signals)
    duration_s: Mapped[float | None] = mapped_column(Float)
    avg_hr: Mapped[float | None] = mapped_column(Float)
    max_hr: Mapped[float | None] = mapped_column(Float)
    min_hr: Mapped[float | None] = mapped_column(Float)
    training_load: Mapped[float | None] = mapped_column(Float)
    movement_load: Mapped[float | None] = mapped_column(Float)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    signals: Mapped[dict[str, Any] | None] = deferred(mapped_column(JSONB))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
