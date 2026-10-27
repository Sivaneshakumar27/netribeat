"""Recorded sessions: the database table, API schemas, rules and the /api/v1/sessions routes.

A `user` sees and uploads only their own sessions; an `admin` sees all and uploads for anyone.
Upload → hex_decoder → analysis (below) → stored here → served to the app, PDF and exports.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from pydantic import Field
from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Select,
    String,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, deferred, mapped_column, undefer

from netribeat.auth import audit
from netribeat.auth.deps import ClockDep, ContextDep, CurrentUser, DbDep
from netribeat.auth.models import User
from netribeat.auth.service import RequestContext
from netribeat.clock import Clock
from netribeat.core.api_model import ApiModel, error_responses
from netribeat.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from netribeat.db import Base
from netribeat.engine.algo.heart_rate import hr_time_series
from netribeat.engine.algo.hr_statistics import hr_metrics
from netribeat.engine.algo.hrv_td_fd_nl.frequency_domain import lomb_scargle_frequency_domain
from netribeat.engine.algo.hrv_td_fd_nl.hrv_analysis import AdvancedOptions, analyse_advanced
from netribeat.engine.algo.hrv_td_fd_nl.nonlinear import poincare
from netribeat.engine.algo.hrv_td_fd_nl.time_domain import basic_time_domain
from netribeat.engine.algo.movement_load import movement_metrics, rms_time_series
from netribeat.engine.algo.respiration_rate import (
    respiratory_per_minute,
    respiratory_rate,
)
from netribeat.engine.algo.training_load import (
    DEFAULT_RESTING_HR,
    hr_zones,
    theoretical_max_hr,
    training_metrics,
    zone_durations_ms,
    zone_thresholds,
)
from netribeat.hex_decoder.decode_hex import start_time_from_filename
from netribeat.hex_decoder.reader import ProcessingError, athlete_name, decode, item
from netribeat.preprocessing.artefact_correction import correct_artefacts
from netribeat.preprocessing.rr_intervals import rr_intervals
from netribeat.reports import exports, pdf

# ================================================================== analysis of one session
# hex_decoder → preprocessing → engine/algo → the metrics and signals stored below.
# Only the inputs (athlete age, gender, max HR, resting HR) and field names are chosen here;
# every number comes from engine/.


ANALYSIS_VERSION = "hex-1.2"
ZONE_KEYS = ["belowZ1", "z1", "z2", "z3", "z4", "z5"]  # engine zones 0-5
HRV_WINDOW_S = 300.0  # spec HRV: first 5 minutes of the corrected RR series
HRV_MIN_BEATS = 30


def analyse_session(
    df: pd.DataFrame,
    age: int | None,
    gender: str | None,
    max_hr: float | None = None,
    resting_hr: int | None = None,
    zones: str = "classic",
) -> dict[str, Any]:
    """Reference engine: HR, training load and movement load for one decoded session.
    Max HR defaults to 210 − 0.65 · age and resting HR to 50 bpm."""
    max_hr = max_hr or theoretical_max_hr(age)
    resting_hr = resting_hr or DEFAULT_RESTING_HR
    hr = hr_time_series(item(df, "hr"))
    rms = rms_time_series(item(df, "rms"))
    return {
        "hr_metrics": hr_metrics(hr["value"]),
        "training_metrics": training_metrics(hr, max_hr, resting_hr, gender, zones),
        "movement_metrics": movement_metrics(rms),
    }


@dataclass(frozen=True)
class Inputs:
    name: str | None
    age: int | None
    gender: str | None  # male | female | other | None
    resting_hr: int | None
    height_cm: int | None
    weight_kg: float | None
    max_hr: float | None  # resolved max HR (override / manual / peak); None -> age formula
    max_hr_label: str
    max_hr_method: str | None


@dataclass(frozen=True)
class Result:
    recorded_at: datetime
    duration_s: float
    metrics: dict[str, Any]
    signals: dict[str, Any]


def _zones_and_load(
    df: pd.DataFrame, hr: pd.DataFrame, inputs: Inputs
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, float] | None, str | None]:
    """Engine output, max HR used, time in zones (s) and why zones/load are missing."""
    peak = hr["value"].max()
    no_max = inputs.max_hr is None and inputs.age is None
    if no_max and not pd.notna(peak):
        return {}, None, None, "No valid heart rate in this recording, so zones can't be worked out"
    reason: str | None = None
    if inputs.gender not in ("male", "female"):
        reason = "Training load needs the athlete's gender (male or female) on upload"
    max_hr = float(peak) if no_max else inputs.max_hr or theoretical_max_hr(inputs.age)
    if reason is None:
        out = analyse_session(df, inputs.age, inputs.gender, max_hr, inputs.resting_hr)
        ms = out["training_metrics"]["hr_zone_durations"]
    else:  # zones need only max HR; training load also needs gender
        out = {}
        resting = inputs.resting_hr or DEFAULT_RESTING_HR
        thresholds = zone_thresholds(max_hr, resting)
        ms = zone_durations_ms(hr["timestamp"], hr_zones(hr["value"], thresholds))
    if no_max:
        hr_max = {
            "value": round(max_hr),
            "method": "observed",
            "label": "Peak HR in this recording (no age or max HR entered)",
            "detail": f"{round(max_hr)} bpm",
        }
        return out, hr_max, {ZONE_KEYS[int(z)]: v / 1000 for z, v in ms.items()}, reason
    hr_max = {
        "value": round(max_hr),
        "method": inputs.max_hr_method or "age",
        "label": inputs.max_hr_label or "Age formula (210 - 0.65 x age)",
        "detail": f"{round(max_hr)} bpm",
    }
    return out, hr_max, {ZONE_KEYS[int(z)]: v / 1000 for z, v in ms.items()}, reason


def _hrv(t: np.ndarray, rr: np.ndarray, duration_s: float) -> dict[str, Any]:
    """Spec HRV (first 5 min, corrected RR) plus the Kubios-style advanced analysis."""
    corr = correct_artefacts(rr) if rr.size else None
    out: dict[str, Any] = {
        "corrected": corr.corrected if corr else rr,
        "flags": corr.flags if corr else np.zeros(0, bool),
        "timeDomain": None,
        "frequencyDomain": None,
        "poincare": None,
        "respiratoryRate": None,
        "perMinute": [],
        "inWindow": 0,
        "unavailable": {},
    }
    if corr is None or rr.size < HRV_MIN_BEATS:
        msg = f"At least {HRV_MIN_BEATS} RR intervals are needed (found {rr.size})"
        out["unavailable"] = {"timeDomain": msg, "frequencyDomain": msg}
    else:
        win = t <= HRV_WINDOW_S
        rr_w, t_w = corr.corrected[win], t[win]
        out["inWindow"] = int(win.sum())
        if rr_w.size >= HRV_MIN_BEATS:
            fd = lomb_scargle_frequency_domain(t_w, rr_w)
            out["timeDomain"] = basic_time_domain(rr_w)
            out["frequencyDomain"] = fd
            out["poincare"] = poincare(rr_w)
            out["respiratoryRate"] = respiratory_rate(fd["bands"]["hf"]["peakHz"])
            out["perMinute"] = respiratory_per_minute(t, corr.corrected, duration_s)
    adv = analyse_advanced(t, rr, AdvancedOptions())
    out["advanced"], out["advancedSeries"] = adv.metrics, adv.series
    return out


def analyse(df: pd.DataFrame, inputs: Inputs) -> Result:
    start = df["timestamp"].min()
    duration_s = float((df["timestamp"].max() - start).total_seconds())
    t0 = start.value // 1_000_000  # epoch ms

    def rel_s(ts: pd.Series) -> list[float]:
        return [round((t.value // 1_000_000 - t0) / 1000, 3) for t in ts]

    hr = hr_time_series(item(df, "hr"))
    engine_out, hr_max, time_in_zones, reason = _zones_and_load(df, hr, inputs)
    if not engine_out:
        engine_out = {
            "hr_metrics": hr_metrics(hr["value"]),
            "movement_metrics": movement_metrics(rms_time_series(item(df, "rms"))),
        }
    hrm, mov = engine_out["hr_metrics"], engine_out["movement_metrics"]
    tm = engine_out.get("training_metrics") or {}

    t_end, rr = rr_intervals(df, t0)
    hrv = _hrv(t_end, rr, duration_s)
    flags = hrv["flags"]
    coverage = float(rr[~flags].sum()) / 1000 / duration_s if duration_s else 0.0
    steps = item(df, "steps")
    rms = rms_time_series(item(df, "rms"))
    hr_valid = hr.dropna(subset=["value"])

    metrics = {
        "analysisVersion": ANALYSIS_VERSION,
        "source": {"format": "Synapse hex", "unit": "RR from the sensor", "samplingRateHz": None},
        "quality": None,
        "reliability": {"reliable": True, "beatCoverage": round(min(coverage, 1.0), 3)},
        "beats": {
            "detected": int(rr.size),
            "rrIntervals": int(rr.size),
            "artefacts": int(flags.sum()),
            "artefactPct": round(100 * float(flags.mean()), 2) if flags.size else 0,
        },
        "hr": {"avg": hrm["avg_hr"], "min": hrm["min_hr"], "max": hrm["max_hr"]},
        "hrMax": hr_max,
        "timeInZonesS": time_in_zones,
        "zonesUnavailableReason": reason,
        "trainingLoad": tm.get("training_load"),
        "trainingIntensity": tm.get("training_intensity"),
        "movementLoad": mov["movement_load"],
        "movementIntensity": mov["movement_intensity"],
        "steps": int(steps["value"].sum()),
        "subject": {
            "name": inputs.name,
            "age": inputs.age,
            "gender": inputs.gender,
            "restingHr": inputs.resting_hr,
            "heightCm": inputs.height_cm,
            "weightKg": inputs.weight_kg,
            "maxHr": hr_max["value"] if hr_max else None,
        },
        "engine": engine_out,  # the engine's own output, unchanged
        "timeDomain": hrv["timeDomain"],
        "frequencyDomain": hrv["frequencyDomain"],
        "poincare": hrv["poincare"],
        "respiratoryRate": hrv["respiratoryRate"],
        "advanced": hrv["advanced"],
        "unavailable": {
            **hrv["unavailable"],
            "movementLoad": (
                f"{_num(mov['movement_load'])} RMS-hours · "
                f"intensity {_num(mov['movement_intensity'])}"
            ),
        },
        "warnings": [],
        "provisionalRules": {},
    }
    signals = {
        "hr": {"tS": rel_s(hr_valid["timestamp"]), "bpm": hr_valid["value"].tolist()},
        "beatTimesS": np.round(t_end, 3).tolist(),
        "rrRawMs": rr.tolist(),
        "rrCorrectedMs": np.round(hrv["corrected"], 2).tolist(),
        "artefactIndices": np.flatnonzero(flags).tolist(),
        "hrvWindowBeats": hrv["inWindow"],
        "ecgStrip": None,
        "perMinute": {"respiratoryRate": hrv["perMinute"]},
        "rms": {"tS": rel_s(rms["timestamp"]), "value": rms["value"].tolist()},
        "steps": {"tS": rel_s(steps["timestamp"]), "value": steps["value"].tolist()},
        "advanced": hrv["advancedSeries"],
    }
    return Result(
        recorded_at=start.to_pydatetime().astimezone(UTC),
        duration_s=round(duration_s, 1),
        metrics=json_safe(metrics),
        signals=json_safe(signals),
    )


def reanalyse_advanced(signals: dict[str, Any], options: dict[str, Any]) -> tuple[Any, Any]:
    """Advanced HRV again with the user's options (sample, correction, detrending)."""
    opts = AdvancedOptions(**options).validated()
    t = np.asarray(signals.get("beatTimesS", []), dtype=float)
    rr = np.asarray(signals.get("rrRawMs", []), dtype=float)
    adv = analyse_advanced(t, rr, opts)
    return json_safe(adv.metrics), json_safe(adv.series)


def _num(v: Any) -> str:
    return "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:g}"


def json_safe(value: Any) -> Any:
    """NaN / inf -> None and numpy values -> Python, so the result can be stored as JSON."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


# ================================================================== database table


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
    # Athlete details entered on upload (optional; never taken from the account profile)
    athlete_name: Mapped[str | None] = mapped_column(String(100))  # empty -> from the file name
    age: Mapped[int | None]
    age_source: Mapped[str] = mapped_column(String(10))  # entered | none
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
    rmssd: Mapped[float | None] = mapped_column(Float)
    movement_load: Mapped[float | None] = mapped_column(Float)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    signals: Mapped[dict[str, Any] | None] = deferred(mapped_column(JSONB))

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


# ================================================================== API schemas


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
    training_load_reason: str | None = None
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


class AdvancedOptionsIn(ApiModel):
    """Options for the Kubios-style HRV analysis. Unset fields keep their defaults."""

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
    session_id: uuid.UUID
    metrics: dict[str, Any]
    series: dict[str, Any]


# ============================================================ rules: upload, analysis, visibility


MAX_FILES = 10
MAX_FILE_BYTES = 20 * 1024 * 1024
LABELS = {"override": "Upload override", "age": "Age formula (210 - 0.65 x age)"}


@dataclass(frozen=True)
class UploadForm:
    type: str
    device: str
    recorded_at: datetime | None
    age: int | None
    hr_max_manual: int | None
    notes: str | None
    user_id: uuid.UUID | None  # admins only
    # Athlete details (optional; never taken from the account profile)
    athlete_name: str | None = None  # empty -> from the file name
    gender: str | None = None
    resting_hr: int | None = None
    height_cm: int | None = None
    weight_kg: float | None = None


def _visible(stmt: Select[tuple[Recording]], user: User) -> Select[tuple[Recording]]:
    return stmt if user.is_admin else stmt.where(Recording.user_id == user.id)


async def get_recording(
    db: AsyncSession, user: User, session_id: uuid.UUID, *, full: bool = False
) -> Recording:
    stmt = _visible(select(Recording).where(Recording.id == session_id), user)
    if full:
        stmt = stmt.options(undefer(Recording.signals), undefer(Recording.file_data))
    rec = (await db.execute(stmt)).scalar_one_or_none()
    if rec is None:
        raise NotFound("Session not found")
    return rec


async def load_owners(db: AsyncSession, recs: Sequence[Recording]) -> dict[uuid.UUID, User]:
    ids = {r.user_id for r in recs}
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars()
    return {u.id: u for u in rows}


async def query_sessions(
    db: AsyncSession,
    user: User,
    *,
    q: str | None,
    user_id: uuid.UUID | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[Sequence[Recording], int, dict[str, float | int | None]]:
    stmt = _visible(select(Recording), user)
    if user_id:
        stmt = stmt.where(Recording.user_id == user_id)
    if status:
        stmt = stmt.where(Recording.status == status)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.join(User, User.id == Recording.user_id).where(
            or_(
                func.lower(Recording.file_name).like(like),
                func.lower(User.email).like(like),
                func.lower(User.first_name + " " + User.last_name).like(like),
                Recording.notes.ilike(like),
            )
        )
    sub = stmt.subquery()
    total, users, seconds = (
        await db.execute(
            select(
                func.count(), func.count(func.distinct(sub.c.user_id)), func.sum(sub.c.duration_s)
            )
        )
    ).one()
    rows = (
        (
            await db.execute(
                stmt.order_by(Recording.recorded_at.desc(), Recording.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    stats = {"sessions": total, "users": users, "recorded_time_s": float(seconds or 0)}
    return rows, int(total), stats


# ------------------------------------------------------------------ max HR


def _inputs(rec: Recording) -> Inputs:
    """Athlete details from this upload only (one account tests many athletes, so the account
    profile is never used): entered values, the name from the file name, otherwise None."""
    used = "override" if rec.hr_max_manual else "age" if rec.age is not None else None
    return Inputs(
        name=athlete_name(rec.athlete_name, rec.file_name),
        age=rec.age,
        gender=rec.gender,
        resting_hr=rec.resting_hr,
        height_cm=rec.height_cm,
        weight_kg=rec.weight_kg,
        max_hr=float(rec.hr_max_manual) if rec.hr_max_manual else None,
        max_hr_label=LABELS[used] if used else "",
        max_hr_method=used,
    )


# ------------------------------------------------------------------ upload and analysis


async def _apply(
    db: AsyncSession, clock: Clock, rec: Recording, owner: User, df: pd.DataFrame
) -> None:
    rec.attempts += 1
    rec.processed_at = clock.now()
    try:
        result = await asyncio.to_thread(analyse, df, _inputs(rec))
    except ValueError as exc:  # the engine's own "can't analyse" errors
        rec.status, rec.error = "failed", str(exc)[:500]
        return
    m = result.metrics
    rec.status, rec.error = "ready", None
    if rec.recorded_at_source == "file":  # else keep the entered / upload time (stable re-runs)
        rec.recorded_at = result.recorded_at
    rec.duration_s = result.duration_s
    rec.avg_hr, rec.max_hr, rec.min_hr = m["hr"]["avg"], m["hr"]["max"], m["hr"]["min"]
    rec.training_load, rec.movement_load = m["trainingLoad"], m["movementLoad"]
    rec.rmssd = (m.get("timeDomain") or {}).get("rmssd")
    rec.metrics, rec.signals = m, result.signals


def _fallback_start_ms(rec: Recording) -> int:
    return int(rec.recorded_at.timestamp() * 1000)


async def reanalyse(db: AsyncSession, clock: Clock, rec: Recording, owner: User) -> None:
    """Analyse a stored session again from its original file."""
    try:
        sessions = await asyncio.to_thread(
            decode, rec.file_data, rec.file_name, _fallback_start_ms(rec)
        )
        if rec.part >= len(sessions):
            raise ProcessingError("The session is no longer found in the file")
        await _apply(db, clock, rec, owner, sessions[rec.part])
    except ProcessingError as exc:
        rec.attempts += 1
        rec.status, rec.error = "failed", str(exc)
    await db.commit()


async def save_uploads(
    db: AsyncSession,
    clock: Clock,
    *,
    actor: User,
    files: list[tuple[str, bytes]],
    form: UploadForm,
    ctx: RequestContext,
) -> list[Recording]:
    if not files:
        raise ValidationFailed(fields={"files": "Choose at least one hex file"})
    if len(files) > MAX_FILES:
        raise ValidationFailed(fields={"files": f"Upload at most {MAX_FILES} files at once"})
    owner = actor
    if form.user_id and form.user_id != actor.id:
        if not actor.is_admin:
            raise Forbidden("You can only upload your own sessions")
        found = await db.get(User, form.user_id)
        if found is None:
            raise ValidationFailed(fields={"userId": "User not found"})
        owner = found

    now = clock.now()
    fallback = form.recorded_at or now
    decoded: list[tuple[str, bytes, list[pd.DataFrame]]] = []
    problems: dict[str, str] = {}
    for i, (name, data) in enumerate(files):
        if len(data) > MAX_FILE_BYTES:
            problems[f"files.{i}"] = f"{name}: larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"
            continue
        try:
            sessions = await asyncio.to_thread(decode, data, name, int(fallback.timestamp() * 1000))
        except ProcessingError as exc:
            problems[f"files.{i}"] = f"{name}: {exc}"
            continue
        decoded.append((name, data, sessions))
    if problems:
        raise ValidationFailed("Some files can't be analysed", fields=problems)

    created: list[Recording] = []
    for name, data, sessions in decoded:
        from_file = start_time_from_filename(name) is not None
        for part, df in enumerate(sessions):
            rec = Recording(
                user_id=owner.id,
                uploaded_by_id=actor.id,
                type=form.type,
                device=form.device,
                notes=form.notes,
                age=form.age,
                age_source="entered" if form.age is not None else "none",
                hr_max_manual=form.hr_max_manual,
                athlete_name=(form.athlete_name or "").strip() or None,
                gender=form.gender,
                resting_hr=form.resting_hr,
                height_cm=form.height_cm,
                weight_kg=form.weight_kg,
                recorded_at=fallback,
                recorded_at_source="file"
                if from_file
                else "entered"
                if form.recorded_at
                else "upload",
                file_name=name[:255],
                file_size=len(data),
                file_data=data,
                part=part,
                status="processing",
                attempts=0,
            )
            db.add(rec)
            await _apply(db, clock, rec, owner, df)
            created.append(rec)
    await db.flush()
    audit.record(
        db,
        action="session.uploaded",
        now=now,
        actor_id=actor.id,
        target_id=owner.id,
        ip=ctx.ip,
        details={"sessions": len(created), "files": len(decoded)},
    )
    await db.commit()
    return created


async def delete_recording(
    db: AsyncSession, clock: Clock, user: User, rec: Recording, ctx: RequestContext
) -> None:
    if not user.is_admin and rec.user_id != user.id:
        raise Forbidden()
    audit.record(
        db,
        action="session.deleted",
        now=clock.now(),
        actor_id=user.id,
        target_id=rec.user_id,
        ip=ctx.ip,
        details={"session_id": str(rec.id)},
    )
    await db.delete(rec)
    await db.commit()


async def upgrade_hrv(db: AsyncSession, rec: Recording) -> Recording:
    """Sessions analysed before the corrected RR series existed get it on first view: the
    advanced HRV is run again with its saved options (same results, one extra series)."""
    tach = ((rec.signals or {}).get("advanced") or {}).get("tachogram") or {}
    if not tach or "rrCorrectedMs" in tach:
        return rec
    options = ((rec.metrics or {}).get("advanced") or {}).get("options") or {}
    try:
        metrics, series = await asyncio.to_thread(reanalyse_advanced, rec.signals or {}, options)
    except (TypeError, ValueError):
        return rec  # keep the stored result; the chart then shows raw RR
    rec.metrics = {**(rec.metrics or {}), "advanced": metrics}
    rec.signals = {**(rec.signals or {}), "advanced": series}
    await db.commit()
    return rec


async def reanalyse_hrv(
    db: AsyncSession,
    clock: Clock,
    user: User,
    rec: Recording,
    options: dict[str, object],
    ctx: RequestContext,
) -> Recording:
    """Advanced HRV again with new options; stored, so the screens and the PDF agree."""
    try:
        metrics, series = await asyncio.to_thread(reanalyse_advanced, rec.signals or {}, options)
    except (TypeError, ValueError) as exc:
        raise ValidationFailed(str(exc), fields={"options": str(exc)}) from None
    rec.metrics = {**(rec.metrics or {}), "advanced": metrics}
    rec.signals = {**(rec.signals or {}), "advanced": series}
    audit.record(
        db,
        action="session.reanalysed",
        now=clock.now(),
        actor_id=user.id,
        target_id=rec.user_id,
        ip=ctx.ip,
        details={"session_id": str(rec.id)},
    )
    await db.commit()
    return rec


# ================================================================== routes


router = APIRouter(prefix="/sessions", tags=["Sessions"])
E = error_responses(400, 401, 404)


def _load_reason(rec: Recording) -> str:
    if rec.status != "ready":
        return "The session hasn't been analysed yet"
    if rec.gender not in ("male", "female"):
        return "Needs the athlete's gender (male or female) on upload"
    return "No valid heart rate to compute it from"


def _summary(rec: Recording, owner: User | None) -> dict[str, object]:
    return {
        "id": rec.id,
        "user_id": rec.user_id,
        "user_email": owner.email if owner else None,
        "user_name": owner.display_name if owner else "Deleted user",
        "type": rec.type,
        "recorded_at": rec.recorded_at,
        "duration_s": rec.duration_s,
        "status": rec.status,
        "quality": None,
        "reliable": True if rec.status == "ready" else None,
        "avg_hr": rec.avg_hr,
        "max_hr": rec.max_hr,
        "min_hr": rec.min_hr,
        "rmssd": round(rec.rmssd, 1) if rec.rmssd is not None else None,
        "training_load": rec.training_load,
        "training_load_reason": None if rec.training_load is not None else _load_reason(rec),
        "movement_load": rec.movement_load,
        "file_name": rec.file_name,
    }


def _detail(rec: Recording, owner: User | None) -> SessionOut:
    return SessionOut(
        **_summary(rec, owner),
        age=rec.age,
        age_source=rec.age_source,
        recorded_at_source=rec.recorded_at_source,
        device=rec.device,
        notes=rec.notes,
        hr_max_manual=rec.hr_max_manual,
        files=[
            FileInfo(
                id=rec.id,
                name=rec.file_name,
                kind="rr",
                format="synapse_hex",
                size_bytes=rec.file_size,
            )
        ],
        artefact_count=None,
        artefact_pct=None,
        hrv_window_s=[],
        error=rec.error,
        attempts=rec.attempts,
        created_at=rec.created_at,
        processed_at=rec.processed_at,
    )


async def _with_owner(db: DbDep, rec: Recording) -> SessionOut:
    return _detail(rec, await db.get(User, rec.user_id))


async def _ready(db: DbDep, user: User, session_id: uuid.UUID) -> Recording:
    rec = await get_recording(db, user, session_id, full=True)
    if rec.status != "ready":
        raise Conflict("The session has no results yet", code="not_ready")
    return rec


def _download(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("", response_model=SessionList, responses=E, summary="List visible sessions")
async def list_sessions(
    user: CurrentUser,
    db: DbDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    user_id: Annotated[uuid.UUID | None, Query(alias="userId")] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SessionList:
    rows, total, stats = await query_sessions(
        db, user, q=q, user_id=user_id, status=status_, limit=limit, offset=offset
    )
    owners = await load_owners(db, rows)
    return SessionList(
        items=[SessionSummary(**_summary(r, owners.get(r.user_id))) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
        stats=SessionStats(**stats, avg_rmssd=None),
    )


@router.post(
    "",
    response_model=UploadResult,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 413),
    summary="Upload Synapse hex files; each session in a file is analysed",
)
async def upload(
    user: CurrentUser,
    db: DbDep,
    clock: ClockDep,
    ctx: ContextDep,
    files: Annotated[list[UploadFile], File(description="Synapse sensor hex files (.txt)")],
    type_: Annotated[str, Form(alias="type", max_length=20)] = "training",
    device: Annotated[str, Form(max_length=40)] = "synapse",
    recorded_at: Annotated[datetime | None, Form(alias="recordedAt")] = None,
    age: Annotated[int | None, Form(ge=8, le=100)] = None,
    hr_max_manual: Annotated[int | None, Form(alias="hrMaxManual", ge=100, le=230)] = None,
    notes: Annotated[str | None, Form(max_length=500)] = None,
    user_id: Annotated[uuid.UUID | None, Form(alias="userId")] = None,
    athlete_name: Annotated[str | None, Form(alias="athleteName", max_length=100)] = None,
    gender: Annotated[Literal["male", "female", "other"] | None, Form()] = None,
    resting_hr: Annotated[int | None, Form(alias="restingHr", ge=25, le=120)] = None,
    height_cm: Annotated[int | None, Form(alias="heightCm", ge=80, le=250)] = None,
    weight_kg: Annotated[float | None, Form(alias="weightKg", ge=20, le=300)] = None,
) -> UploadResult:
    data = [(f.filename or "recording.txt", await f.read()) for f in files]
    form = UploadForm(
        type=type_,
        device=device,
        recorded_at=recorded_at,
        age=age,
        hr_max_manual=hr_max_manual,
        notes=notes,
        user_id=user_id,
        athlete_name=athlete_name,
        gender=gender,
        resting_hr=resting_hr,
        height_cm=height_cm,
        weight_kg=weight_kg,
    )
    created = await save_uploads(db, clock, actor=user, files=data, form=form, ctx=ctx)
    owners = await load_owners(db, created)
    return UploadResult(items=[_detail(r, owners.get(r.user_id)) for r in created])


@router.get("/{session_id}", response_model=SessionOut, responses=E, summary="One session")
async def get_session(session_id: uuid.UUID, user: CurrentUser, db: DbDep) -> SessionOut:
    return await _with_owner(db, await get_recording(db, user, session_id))


@router.get("/{session_id}/analysis", response_model=AnalysisOut, responses=E, summary="Metrics")
async def get_analysis(
    session_id: uuid.UUID, user: CurrentUser, db: DbDep, clock: ClockDep
) -> AnalysisOut:
    rec = await _ready(db, user, session_id)
    if (rec.metrics or {}).get("analysisVersion") != ANALYSIS_VERSION:
        # Older results (e.g. no zones without age) are rebuilt once from the stored file.
        owner = await db.get(User, rec.user_id)
        if owner is not None:
            await reanalyse(db, clock, rec, owner)
    return AnalysisOut(session_id=rec.id, metrics=rec.metrics or {})


@router.get("/{session_id}/signals", response_model=SignalsOut, responses=E, summary="Series")
async def get_signals(session_id: uuid.UUID, user: CurrentUser, db: DbDep) -> SignalsOut:
    rec = await upgrade_hrv(db, await _ready(db, user, session_id))
    return SignalsOut(session_id=rec.id, signals=rec.signals or {})


@router.post(
    "/{session_id}/advanced",
    response_model=AdvancedOut,
    responses=error_responses(400, 401, 404, 409),
    summary="Re-run the Kubios-style HRV analysis (sample, artefact correction, detrending)",
)
async def advanced(
    session_id: uuid.UUID,
    body: AdvancedOptionsIn,
    user: CurrentUser,
    db: DbDep,
    clock: ClockDep,
    ctx: ContextDep,
) -> AdvancedOut:
    rec = await _ready(db, user, session_id)
    rec = await reanalyse_hrv(db, clock, user, rec, body.model_dump(), ctx)
    return AdvancedOut(
        session_id=rec.id,
        metrics=(rec.metrics or {})["advanced"],
        series=(rec.signals or {})["advanced"],
    )


@router.get("/{session_id}/report", responses=E, summary="PDF report")
async def report(session_id: uuid.UUID, user: CurrentUser, db: DbDep, clock: ClockDep) -> Response:
    rec = await _ready(db, user, session_id)
    content = pdf.render(rec, clock.now())
    return _download(content, "application/pdf", f"netribeat-session-{str(rec.id)[:8]}.pdf")


@router.get("/{session_id}/export.json", responses=E, summary="All results as JSON")
async def export_json(
    session_id: uuid.UUID, user: CurrentUser, db: DbDep, clock: ClockDep
) -> Response:
    rec = await _ready(db, user, session_id)
    return _download(
        exports.to_json(rec, clock.now()),
        "application/json",
        f"netribeat-session-{str(rec.id)[:8]}.json",
    )


@router.get("/{session_id}/export.csv", responses=E, summary="Metrics or a series as CSV")
async def export_csv(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DbDep,
    dataset: Annotated[str, Query(pattern="^(metrics|hr|rr|rms|psd)$")] = "metrics",
) -> Response:
    if dataset == "psd":
        raise NotFound("There is no spectrum for sensor hex files")
    rec = await _ready(db, user, session_id)
    return _download(
        exports.to_csv(rec, dataset),
        "text/csv",
        f"netribeat-session-{str(rec.id)[:8]}-{dataset}.csv",
    )


@router.get("/{session_id}/files/{file_id}", responses=E, summary="The original uploaded file")
async def original(
    session_id: uuid.UUID, file_id: uuid.UUID, user: CurrentUser, db: DbDep
) -> Response:
    rec = await get_recording(db, user, session_id, full=True)
    if file_id != rec.id:
        raise NotFound()
    return _download(rec.file_data, "text/plain", rec.file_name.replace('"', ""))


@router.delete(
    "/{session_id}", status_code=status.HTTP_204_NO_CONTENT, responses=E, summary="Delete"
)
async def delete_session(
    session_id: uuid.UUID, user: CurrentUser, db: DbDep, clock: ClockDep, ctx: ContextDep
) -> Response:
    rec = await get_recording(db, user, session_id)
    await delete_recording(db, clock, user, rec, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{session_id}/retry", response_model=SessionOut, responses=E, summary="Analyse again")
async def retry(session_id: uuid.UUID, user: CurrentUser, db: DbDep, clock: ClockDep) -> SessionOut:
    rec = await get_recording(db, user, session_id, full=True)
    owner = await db.get(User, rec.user_id)
    if owner is None:
        raise NotFound()
    await reanalyse(db, clock, rec, owner)
    return _detail(rec, owner)
