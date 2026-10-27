"""Run the engine on a hex file and shape its output for the API and the frontend.

All numbers come from the engine (netribeat/engine). This file only picks the session out of
the file, chooses the inputs (age, gender, max HR, resting HR) and renames fields.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from netribeat import engine

ANALYSIS_VERSION = "hex-1.0"
ZONE_KEYS = ["belowZ1", "z1", "z2", "z3", "z4", "z5"]  # engine zones 0-5


class ProcessingError(Exception):
    """A user-facing reason the file can't be analysed."""


@dataclass(frozen=True)
class Inputs:
    age: int | None
    gender: str | None  # male | female | other | None
    resting_hr: int | None
    max_hr: float | None  # resolved max HR (manual / peak / age); None -> unknown
    max_hr_label: str
    max_hr_method: str | None


@dataclass(frozen=True)
class Result:
    recorded_at: datetime
    duration_s: float
    metrics: dict[str, Any]
    signals: dict[str, Any]


def decode(data: bytes, file_name: str, fallback_start_ms: int) -> list[pd.DataFrame]:
    """All sessions in a hex file. The start time comes from the file name when it has one."""
    start_ms = engine.start_time_from_filename(file_name) or fallback_start_ms
    try:
        sessions: list[pd.DataFrame] = engine.decode_hex(data, start_ms)
    except UnicodeDecodeError:
        raise ProcessingError("Not a Synapse hex file (the file is not text)") from None
    except ValueError as exc:
        raise ProcessingError(f"Not a usable Synapse hex file: {exc}") from None
    if not sessions:
        raise ProcessingError("The file has no session long enough to analyse")
    return sessions


def analyse(df: pd.DataFrame, inputs: Inputs) -> Result:
    start = df["timestamp"].min()
    duration_s = float((df["timestamp"].max() - start).total_seconds())
    t0 = start.value // 1_000_000  # epoch ms

    hr = engine.hr_time_series(engine.item(df, "hr"))
    warnings: list[str] = []
    engine_out: dict[str, Any] = {}
    zones_reason: str | None = None
    time_in_zones: dict[str, float] | None = None
    load = intensity = None

    if inputs.max_hr is None and inputs.age is None:
        zones_reason = "Enter your age (profile or upload) or set a max HR in Settings"
    elif inputs.gender not in ("male", "female"):
        zones_reason = "Training load needs gender male or female in your profile"
    if inputs.max_hr is not None or inputs.age is not None:
        max_hr = inputs.max_hr or engine.theoretical_max_hr(inputs.age)
        if zones_reason is None:
            engine_out = engine.analyse_session(
                df, inputs.age, inputs.gender, max_hr, inputs.resting_hr
            )
            ms = engine_out["training_metrics"]["hr_zone_durations"]
            load = engine_out["training_metrics"]["training_load"]
            intensity = engine_out["training_metrics"]["training_intensity"]
        else:  # zones need only max HR; training load also needs gender
            resting = inputs.resting_hr or engine.DEFAULT_RESTING_HR
            thresholds = engine.zone_thresholds(max_hr, resting)
            ms = engine.zone_durations_ms(hr["timestamp"], engine.hr_zones(hr["value"], thresholds))
        time_in_zones = {ZONE_KEYS[int(z)]: v / 1000 for z, v in ms.items()}
        hr_max = {
            "value": round(max_hr),
            "method": inputs.max_hr_method or "age",
            "label": inputs.max_hr_label,
            "detail": f"{round(max_hr)} bpm",
        }
    else:
        hr_max = None

    if not engine_out:
        engine_out = {
            "hr_metrics": engine.hr_metrics(hr["value"]),
            "movement_metrics": engine.movement_metrics(
                engine.rms_time_series(engine.item(df, "rms"))
            ),
        }
    hrm, mov = engine_out["hr_metrics"], engine_out["movement_metrics"]

    rr = engine.item(df, "rrt")
    beats = rr.dropna(subset=["value"])
    coverage = float(beats["value"].sum()) / 1000 / duration_s if duration_s else 0.0
    steps = engine.item(df, "steps")
    rms = engine.rms_time_series(engine.item(df, "rms"))

    def rel_s(ts: pd.Series) -> list[float]:
        return [round((t.value // 1_000_000 - t0) / 1000, 3) for t in ts]

    hr_valid = hr.dropna(subset=["value"])
    movement_text = (
        f"{_num(mov['movement_load'])} RMS-hours · intensity {_num(mov['movement_intensity'])}"
    )
    metrics = {
        "analysisVersion": ANALYSIS_VERSION,
        "source": {"format": "Synapse hex", "unit": "RR from the sensor", "samplingRateHz": None},
        "quality": None,
        "reliability": {"reliable": True, "beatCoverage": round(min(coverage, 1.0), 3)},
        "beats": {
            "detected": len(rr),
            "rrIntervals": len(beats),
            "artefacts": 0,
            "artefactPct": 0,
        },
        "hr": {"avg": hrm["avg_hr"], "min": hrm["min_hr"], "max": hrm["max_hr"]},
        "hrMax": hr_max,
        "timeInZonesS": time_in_zones,
        "zonesUnavailableReason": zones_reason,
        "trainingLoad": load,
        "trainingIntensity": intensity,
        "movementLoad": mov["movement_load"],
        "movementIntensity": mov["movement_intensity"],
        "steps": int(steps["value"].sum()),
        "inputs": {
            "age": inputs.age,
            "gender": inputs.gender,
            "restingHr": inputs.resting_hr or engine.DEFAULT_RESTING_HR,
            "maxHr": hr_max["value"] if hr_max else None,
        },
        "engine": engine_out,  # the engine's own output, unchanged
        # Not part of the hex method (the frontend shows "not available").
        "timeDomain": None,
        "frequencyDomain": None,
        "poincare": None,
        "respiratoryRate": None,
        "advanced": None,
        "unavailable": {
            "timeDomain": "HRV is not part of the hex-file analysis",
            "frequencyDomain": "HRV is not part of the hex-file analysis",
            "movementLoad": movement_text,
        },
        "warnings": warnings,
        "provisionalRules": {},
    }
    signals = {
        "hr": {"tS": rel_s(hr_valid["timestamp"]), "bpm": hr_valid["value"].tolist()},
        "beatTimesS": rel_s(beats["timestamp"]),
        "rrRawMs": beats["value"].tolist(),
        "rrCorrectedMs": beats["value"].tolist(),
        "artefactIndices": [],
        "hrvWindowBeats": 0,
        "ecgStrip": None,
        "perMinute": {"respiratoryRate": []},
        "rms": {"tS": rel_s(rms["timestamp"]), "value": rms["value"].tolist()},
        "steps": {"tS": rel_s(steps["timestamp"]), "value": steps["value"].tolist()},
        "advanced": None,
    }
    return Result(
        recorded_at=start.to_pydatetime().astimezone(UTC),
        duration_s=round(duration_s, 1),
        metrics=_json_safe(metrics),
        signals=_json_safe(signals),
    )


def _num(v: Any) -> str:
    return "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:g}"


def _json_safe(value: Any) -> Any:
    """NaN / inf -> None and numpy scalars -> Python, so the result can be stored as JSON."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
