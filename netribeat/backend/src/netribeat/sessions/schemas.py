"""Session API schemas (api-spec.yaml SessionSummary / Session / SessionList, with
"athlete" → "user")."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from netribeat.api_model import ApiModel
from netribeat.sessions.models import Device, SessionStatus, SessionType, ValueSource


class FileInfo(ApiModel):
    id: uuid.UUID
    name: str
    kind: str | None
    format: str | None
    size_bytes: int
    sha256: str


class SessionSummary(ApiModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str | None
    user_name: str
    type: SessionType
    recorded_at: datetime
    duration_s: float | None
    status: SessionStatus
    quality: str | None
    reliable: bool | None
    avg_hr: float | None
    max_hr: float | None
    rmssd: float | None
    training_load: float | None
    movement_load: float | None = None
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
    age_source: ValueSource
    recorded_at_source: ValueSource
    device: Device
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
    """Stored metrics (design-spec §6 / api-spec Analysis), plus quality, reliability,
    warnings, unavailable-metric reasons and the provisional rules in force."""

    model_config = {**ApiModel.model_config, "extra": "allow"}
    session_id: uuid.UUID
    metrics: dict[str, Any]


class SignalsOut(ApiModel):
    model_config = {**ApiModel.model_config, "extra": "allow"}
    session_id: uuid.UUID
    signals: dict[str, Any]


class HrMaxSettingsIn(ApiModel):
    method: str  # age | peak | manual
    manual_value: int | None = None


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


class AdvancedOptionsIn(ApiModel):
    """Options for the advanced HRV analysis (Kubios-compatible definitions).
    Unset fields keep their defaults."""

    sample_start_s: float = Field(default=0.0, ge=0, le=86400)
    sample_length_s: float | None = Field(default=300.0, ge=30, le=86400)
    correction: str = Field(
        default="low", pattern="^(none|spec|very_low|low|medium|strong|very_strong)$"
    )
    detrend: str = Field(default="smoothness_priors", pattern="^(none|smoothness_priors)$")
    smoothness_lambda: float = Field(default=500.0, ge=1, le=100000)
    welch_window_s: float = Field(default=256.0, ge=30, le=600)
    ar_order: int = Field(default=16, ge=2, le=40)
    tv_window_s: float = Field(default=60.0, ge=10, le=600)
    tv_step_s: float = Field(default=10.0, ge=1, le=600)


class AdvancedOut(ApiModel):
    model_config = {**ApiModel.model_config, "extra": "allow"}
    session_id: uuid.UUID
    metrics: dict[str, Any]
    series: dict[str, Any]
