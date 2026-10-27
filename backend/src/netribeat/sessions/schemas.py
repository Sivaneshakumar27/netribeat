"""Request/response schemas for /sessions and max-HR settings (field names match the UI)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from netribeat.core.api_model import ApiModel


class FileInfo(ApiModel):
    id: uuid.UUID
    name: str
    kind: str | None
    format: str | None
    size_bytes: int


class SessionSummary(ApiModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str | None
    user_name: str
    type: str
    recorded_at: datetime
    duration_s: float | None
    status: str
    quality: str | None
    reliable: bool | None
    avg_hr: float | None
    max_hr: float | None
    min_hr: float | None
    rmssd: float | None
    training_load: float | None
    movement_load: float | None
    file_name: str


class SessionStats(ApiModel):
    sessions: int
    users: int
    recorded_time_s: float
    avg_rmssd: float | None


class SessionList(ApiModel):
    items: list[SessionSummary]
    total: int
    limit: int
    offset: int
    stats: SessionStats


class SessionOut(SessionSummary):
    age: int | None
    age_source: str
    recorded_at_source: str
    device: str
    notes: str | None
    hr_max_manual: int | None
    files: list[FileInfo]
    artefact_count: int | None
    artefact_pct: float | None
    hrv_window_s: list[float]
    error: str | None
    attempts: int
    created_at: datetime
    processed_at: datetime | None


class UploadResult(ApiModel):
    items: list[SessionOut]


class AnalysisOut(ApiModel):
    session_id: uuid.UUID
    metrics: dict[str, Any]


class SignalsOut(ApiModel):
    session_id: uuid.UUID
    signals: dict[str, Any]


class HrMaxSettingsIn(ApiModel):
    method: Literal["age", "peak", "manual"]
    manual_value: int | None = Field(default=None, ge=100, le=230)


class HrMaxOption(ApiModel):
    method: str
    value: int | None
    detail: str


class HrMaxSettingsOut(ApiModel):
    method: str | None
    manual_value: int | None
    options: list[HrMaxOption]
    effective: HrMaxOption | None
    sessions_ready: int
    recomputed_sessions: int | None = None
