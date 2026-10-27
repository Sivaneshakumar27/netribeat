"""Full session output: runs every algorithm on one decoded session and shapes the result for
the API, the frontend and the PDF.

    hex_decoder → rr_interval → preprocessing → engine/algo/* → metrics (this file)

It only chooses the inputs (athlete age, gender, max HR, resting HR), calls the algorithms and
names the fields; every number comes from engine/ and metrics/derived_metrics + hrv_metrics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from netribeat.engine.algo.hr.heart_rate import hr_time_series
from netribeat.engine.algo.hrv_td_fd_nl.frequency_domain import lomb_scargle_frequency_domain
from netribeat.engine.algo.hrv_td_fd_nl.nonlinear import poincare
from netribeat.engine.algo.hrv_td_fd_nl.time_domain import basic_time_domain
from netribeat.engine.algo.max_min_avg_hr.hr_statistics import hr_metrics
from netribeat.engine.algo.movement_load.movement_load import movement_metrics, rms_time_series
from netribeat.engine.algo.respiration_rate.respiration_rate import (
    respiratory_per_minute,
    respiratory_rate,
)
from netribeat.engine.algo.training_load.training_load import (
    DEFAULT_RESTING_HR,
    hr_zones,
    theoretical_max_hr,
    zone_durations_ms,
    zone_thresholds,
)
from netribeat.metrics.derived_metrics import analyse_session, item
from netribeat.metrics.hrv_metrics import AdvancedOptions, analyse_advanced
from netribeat.preprocessing.artefact_correction import correct_artefacts
from netribeat.rr_interval.rr_intervals import rr_intervals

ANALYSIS_VERSION = "hex-1.1"
ZONE_KEYS = ["belowZ1", "z1", "z2", "z3", "z4", "z5"]  # engine zones 0-5
HRV_WINDOW_S = 300.0  # spec HRV: first 5 minutes of the corrected RR series
HRV_MIN_BEATS = 30


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
    reason: str | None = None
    if inputs.max_hr is None and inputs.age is None:
        reason = "Enter the athlete's age or max HR on upload"
    elif inputs.gender not in ("male", "female"):
        reason = "Training load needs the athlete's gender (male or female) on upload"
    if inputs.max_hr is None and inputs.age is None:
        return {}, None, None, reason

    max_hr = inputs.max_hr or theoretical_max_hr(inputs.age)
    if reason is None:
        out = analyse_session(df, inputs.age, inputs.gender, max_hr, inputs.resting_hr)
        ms = out["training_metrics"]["hr_zone_durations"]
    else:  # zones need only max HR; training load also needs gender
        out = {}
        resting = inputs.resting_hr or DEFAULT_RESTING_HR
        thresholds = zone_thresholds(max_hr, resting)
        ms = zone_durations_ms(hr["timestamp"], hr_zones(hr["value"], thresholds))
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
