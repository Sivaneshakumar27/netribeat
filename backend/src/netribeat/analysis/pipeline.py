"""Run the analysis for one parsed recording.

Stages: beats (R-peaks per segment, or RR from file) → artefact correction → quality →
1 Hz HR → HRV window → time / frequency / Poincaré / respiration. Zone metrics depend
on HRmax and are applied separately (``hr.zone_metrics``) so a settings change can
recompute them from the stored 1 Hz series without re-running ECG processing.
Pure function: no database, no files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from netribeat.analysis import beats as beats_mod
from netribeat.analysis import hrv
from netribeat.analysis.advanced import AdvancedOptions, analyse_advanced
from netribeat.analysis.constants import (
    ANALYSIS_VERSION,
    ECG_STRIP_S,
    HRV_MIN_BEATS,
    HRV_WINDOW_S,
    MIN_BEAT_COVERAGE,
    PROVISIONAL_RULES,
)
from netribeat.analysis.hr import hr_1hz
from netribeat.parsers.base import ParsedRecording, SignalKind


@dataclass
class CoreResult:
    metrics: dict[str, Any]
    signals: dict[str, Any]


def _r(v: float | None, nd: int = 2) -> float | None:
    return None if v is None or not np.isfinite(v) else round(float(v), nd)


def _round_dict(d: dict[str, Any], nd: int = 2) -> dict[str, Any]:
    return {k: (_r(v, nd) if isinstance(v, float) else v) for k, v in d.items()}


def analyse(rec: ParsedRecording) -> CoreResult:
    unavailable: dict[str, str] = {}
    warnings = list(rec.warnings)

    if rec.kind is SignalKind.ECG:
        assert rec.fs_hz is not None
        series, peaks_per_segment = beats_mod.rr_from_ecg(rec.segments, rec.fs_hz)
    else:
        assert rec.rr_ms is not None
        series, peaks_per_segment = beats_mod.rr_from_intervals(rec.rr_ms), []

    corr = beats_mod.correct_artefacts(series.rr_ms)
    quality = beats_mod.quality(series.rr_ms.size, corr.pct)
    t_grid, bpm = hr_1hz(series.t_s, corr.corrected)
    if quality == "no_ecg":
        # Fewer than 30 RR intervals: too few beats for a meaningful heart rate. Report the
        # metric as unavailable instead of numbers from a handful of beats.
        t_grid, bpm = np.empty(0), np.empty(0)

    hr_summary = (
        {"min": _r(bpm.min(), 1), "avg": _r(bpm.mean(), 1), "max": _r(bpm.max(), 1)}
        if bpm.size
        else {"min": None, "avg": None, "max": None}
    )
    if not bpm.size:
        unavailable["hr"] = (
            f"Only {series.rr_ms.size} RR intervals were found (at least 30 are needed); "
            "heart rate, zones and training load are not computed"
        )

    # HRV window: first 300 s of the corrected RR series.
    in_window = series.t_s <= HRV_WINDOW_S
    rr_w, t_w = corr.corrected[in_window], series.t_s[in_window]
    time_domain = frequency = poincare = None
    resp: dict[str, Any] = {"value": None, "hfPeakHz": None}
    if rr_w.size >= HRV_MIN_BEATS and quality != "no_ecg":
        time_domain = _round_dict(hrv.time_domain(rr_w))
        frequency = hrv.frequency_domain(t_w, rr_w)
        frequency["bands"] = {k: _round_dict(b, 4) for k, b in frequency["bands"].items()}
        frequency["power"] = [round(p, 4) for p in frequency["power"]]
        frequency["totalPower"] = _r(frequency["totalPower"])
        frequency["lfHf"] = _r(frequency["lfHf"], 3)
        poincare = _round_dict(hrv.poincare(rr_w))
        resp = hrv.respiratory_rate(frequency["bands"]["hf"]["peakHz"])
        resp = {"value": _r(resp["value"], 1), "hfPeakHz": resp["hfPeakHz"]}
        if series.t_s[-1] < HRV_WINDOW_S:
            warnings.append(
                f"Recording is shorter than the 5-minute HRV window "
                f"({series.t_s[-1]:.0f} s); HRV uses the available beats"
            )
    else:
        reason = (
            f"HRV needs at least {HRV_MIN_BEATS} RR intervals in the first 5 minutes "
            f"(found {rr_w.size})"
        )
        for key in ("timeDomain", "frequencyDomain", "poincare", "respiratoryRate"):
            unavailable[key] = reason
    unavailable["movementLoad"] = "No accelerometer data in this recording"

    coverage = (
        float(series.rr_ms[~corr.flags].sum() / 1000.0 / rec.duration_s)
        if rec.duration_s > 0 and series.rr_ms.size
        else 0.0
    )
    reliable = coverage >= MIN_BEAT_COVERAGE
    if not reliable:
        warnings.insert(
            0,
            (
                f"Beat detection is unreliable: valid beats cover only {coverage * 100:.0f} % of "
                "the recording (expected ≥ 80 %). Strong noise or motion artefacts probably hid "
                "many beats. Treat heart rate, HRV and load values as unreliable."
            ),
        )
    if corr.count:
        warnings.append(
            f"{corr.count} beats ({corr.pct:.1f} %) were corrected as artefacts — all HRV "
            "results use the corrected series"
        )

    metrics: dict[str, Any] = {
        "analysisVersion": ANALYSIS_VERSION,
        "source": {
            "format": rec.format,
            "kind": rec.kind.value,
            "samplingRateHz": rec.fs_hz,
            "unit": rec.unit,
            "durationS": _r(rec.duration_s, 1),
            "segments": len(rec.segments) if rec.segments else None,
            "missingFraction": _r(rec.missing_fraction, 5),
        },
        "quality": quality,
        "hr": hr_summary,
        "beats": {
            "detected": int(series.peaks_detected),
            "rrIntervals": int(series.rr_ms.size),
            "artefacts": corr.count,
            "artefactPct": _r(corr.pct, 2),
        },
        "reliability": {
            "beatCoverage": _r(coverage, 3),
            "minBeatCoverage": MIN_BEAT_COVERAGE,
            "reliable": reliable,
        },
        "hrvWindowS": [0.0, HRV_WINDOW_S],
        "timeDomain": time_domain,
        "frequencyDomain": frequency,
        "poincare": poincare,
        "respiratoryRate": resp,
        "movementLoad": None,
        "warnings": warnings,
        "unavailable": unavailable,
        "provisionalRules": PROVISIONAL_RULES,
    }

    strip = None
    if rec.kind is SignalKind.ECG and rec.segments:
        fs = float(rec.fs_hz or 0)
        first = rec.segments[0]
        n = min(first.samples.size, int(ECG_STRIP_S * fs))
        peaks = peaks_per_segment[0] if peaks_per_segment else np.empty(0, dtype=np.int64)
        strip = {
            "fs": fs,
            "unit": rec.unit,
            "lead": "ECG · chest strap",
            "signal": [round(float(v), 5) for v in first.samples[:n]],
            "rPeaks": [int(p) for p in peaks if p < n],
        }
    signals = {
        "hr": {"tS": t_grid.tolist(), "bpm": [round(float(v), 2) for v in bpm]},
        "beatTimesS": [round(float(v), 3) for v in series.t_s],
        "rrRawMs": [round(float(v), 2) for v in series.rr_ms],
        "rrCorrectedMs": [round(float(v), 2) for v in corr.corrected],
        "artefactIndices": np.flatnonzero(corr.flags).tolist(),
        "hrvWindowBeats": int(in_window.sum()),
        "ecgStrip": strip,
        "perMinute": {
            "movementLoad": None,
            "respiratoryRate": (
                hrv.respiratory_per_minute(series.t_s, corr.corrected, rec.duration_s)
                if quality != "no_ecg"
                else []
            ),
        },
    }
    advanced = analyse_advanced(series.t_s, series.rr_ms, AdvancedOptions())
    metrics["advanced"] = advanced.metrics
    signals["advanced"] = advanced.series
    return CoreResult(metrics=metrics, signals=signals)
