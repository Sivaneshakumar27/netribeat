"""Run the analysis on a hex file and shape its output for the API, the frontend and the PDF.

* engine/  (unchanged reference code): decoding, HR, zones, training load, movement load.
* hrv/     Kubios-style HRV from the decoded RR intervals: time and frequency domain,
           Poincaré, nonlinear, ANS components, respiratory rate.

This file only picks the session out of the file, chooses the inputs (age, gender, max HR,
resting HR) and renames fields.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from netribeat.sessions import engine
from netribeat.sessions.hrv import spectral
from netribeat.sessions.hrv.advanced import AdvancedOptions, analyse_advanced
from netribeat.sessions.hrv.artefacts import correct_artefacts

ANALYSIS_VERSION = "hex-1.1"
ZONE_KEYS = ["belowZ1", "z1", "z2", "z3", "z4", "z5"]  # engine zones 0-5
HRV_WINDOW_S = 300.0  # spec HRV: first 5 minutes of the corrected RR series
HRV_MIN_BEATS = 30


_NAMED_FILE = re.compile(r"^(?P<name>.+?)_\d{4}-\d{2}-\d{2}_\d{2}_\d{2}_\d{2}$")


def name_from_filename(file_name: str) -> str | None:
    """The athlete name in `NAME_YYYY-MM-DD_HH_MM_SS.txt`, or None for other file names."""
    stem = file_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    m = _NAMED_FILE.match(stem)
    return m["name"].replace("_", " ").strip() or None if m else None


def athlete_name(entered: str | None, file_name: str) -> str | None:
    """Entered on upload first, then the file name; None when neither has one."""
    return (entered or "").strip() or name_from_filename(file_name)


class ProcessingError(Exception):
    """A user-facing reason the file can't be analysed."""


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


def _zones_and_load(
    df: pd.DataFrame, hr: pd.DataFrame, inputs: Inputs
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, float] | None, str | None]:
    """Engine output, max HR used, time in zones (s) and why zones/load are missing."""
    reason: str | None = None
    if inputs.max_hr is None and inputs.age is None:
        reason = "Enter age (on upload or in your profile) or set a max HR in Settings"
    elif inputs.gender not in ("male", "female"):
        reason = "Training load needs gender male or female (on upload or in your profile)"
    if inputs.max_hr is None and inputs.age is None:
        return {}, None, None, reason

    max_hr = inputs.max_hr or engine.theoretical_max_hr(inputs.age)
    if reason is None:
        out = engine.analyse_session(df, inputs.age, inputs.gender, max_hr, inputs.resting_hr)
        ms = out["training_metrics"]["hr_zone_durations"]
    else:  # zones need only max HR; training load also needs gender
        out = {}
        resting = inputs.resting_hr or engine.DEFAULT_RESTING_HR
        thresholds = engine.zone_thresholds(max_hr, resting)
        ms = engine.zone_durations_ms(hr["timestamp"], engine.hr_zones(hr["value"], thresholds))
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
            fd = spectral.frequency_domain(t_w, rr_w)
            out["timeDomain"] = spectral.time_domain(rr_w)
            out["frequencyDomain"] = fd
            out["poincare"] = spectral.poincare(rr_w)
            out["respiratoryRate"] = spectral.respiratory_rate(fd["bands"]["hf"]["peakHz"])
            out["perMinute"] = spectral.respiratory_per_minute(t, corr.corrected, duration_s)
    adv = analyse_advanced(t, rr, AdvancedOptions())
    out["advanced"], out["advancedSeries"] = adv.metrics, adv.series
    return out


def analyse(df: pd.DataFrame, inputs: Inputs) -> Result:
    start = df["timestamp"].min()
    duration_s = float((df["timestamp"].max() - start).total_seconds())
    t0 = start.value // 1_000_000  # epoch ms

    def rel_s(ts: pd.Series) -> list[float]:
        return [round((t.value // 1_000_000 - t0) / 1000, 3) for t in ts]

    hr = engine.hr_time_series(engine.item(df, "hr"))
    engine_out, hr_max, time_in_zones, reason = _zones_and_load(df, hr, inputs)
    if not engine_out:
        engine_out = {
            "hr_metrics": engine.hr_metrics(hr["value"]),
            "movement_metrics": engine.movement_metrics(
                engine.rms_time_series(engine.item(df, "rms"))
            ),
        }
    hrm, mov = engine_out["hr_metrics"], engine_out["movement_metrics"]
    tm = engine_out.get("training_metrics") or {}

    # Beats: "rrt" is the RR from each beat to the next; a beat's RR ends at t + RR.
    beats = engine.item(df, "rrt").dropna(subset=["value"])
    rr = beats["value"].to_numpy(dtype=float)
    t_end = np.asarray(rel_s(beats["timestamp"]), dtype=float) + rr / 1000
    hrv = _hrv(t_end, rr, duration_s)
    flags = hrv["flags"]
    coverage = float(rr[~flags].sum()) / 1000 / duration_s if duration_s else 0.0
    steps = engine.item(df, "steps")
    rms = engine.rms_time_series(engine.item(df, "rms"))
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
