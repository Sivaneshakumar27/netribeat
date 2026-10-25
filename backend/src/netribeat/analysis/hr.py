"""1 Hz heart rate (P3), HRmax selection, zones and Edwards TRIMP (design-spec §6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from netribeat.analysis.constants import HRMAX_AGE_BASE, P3_HR_GRID_S, ZONE_EDGES_PCT

F = npt.NDArray[np.float64]
ZONE_KEYS = ("belowZ1", "z1", "z2", "z3", "z4", "z5")


def hr_1hz(t_s: F, rr_corrected_ms: F) -> tuple[F, F]:
    """P3: linear interpolation of corrected beat HR (60 000 / RR) onto a 1 s grid that
    lies within the span of the beats."""
    if t_s.size < 2:
        return np.empty(0), np.empty(0)
    grid = np.arange(np.ceil(t_s[0]), np.floor(t_s[-1]) + P3_HR_GRID_S / 2, P3_HR_GRID_S)
    bpm = np.interp(grid, t_s, 60000.0 / rr_corrected_ms)
    return grid, bpm


@dataclass(frozen=True)
class HrMax:
    value: int
    method: str  # age | peak | manual
    label: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "method": self.method,
            "label": self.label,
            "detail": self.detail,
        }


def resolve_hr_max(
    *,
    user_method: str | None,
    user_manual: int | None,
    user_peak: float | None,
    session_override: int | None,
    age_at_recording: int | None,
) -> HrMax | None:
    """design-spec §6: the user's saved setting → else the session's upload override →
    else age-based (age at recording). None when nothing is known."""
    if user_method == "manual" and user_manual is not None:
        return HrMax(int(user_manual), "manual", "Manual", f"{user_manual} bpm set in Settings")
    if user_method == "peak" and user_peak is not None:
        v = round(user_peak)
        return HrMax(v, "peak", "Session peaks", "Highest max HR across your sessions")
    if user_method == "age" and age_at_recording is not None:
        v = HRMAX_AGE_BASE - age_at_recording
        return HrMax(v, "age", "Age-based", f"210 − age (age {age_at_recording})")
    if session_override is not None:
        return HrMax(
            int(session_override), "manual", "Session override", "Max HR entered at upload"
        )
    if age_at_recording is not None:
        v = HRMAX_AGE_BASE - age_at_recording
        return HrMax(v, "age", "Age-based", f"210 − age (age {age_at_recording})")
    return None


def zone_index(bpm: F, hr_max: float) -> npt.NDArray[np.int64]:
    """0 = below Z1 (< 50 %), 1 = Z1 [50, 60), …, 5 = Z5 (≥ 90 %)."""
    pct = 100.0 * bpm / hr_max
    return np.searchsorted(np.asarray(ZONE_EDGES_PCT), pct, side="right").astype(np.int64)


def zone_metrics(bpm_1hz: F, hr_max: HrMax | None) -> dict[str, Any]:
    if hr_max is None:
        return {
            "hrMax": None,
            "timeInZonesS": None,
            "trainingLoad": None,
            "zonesUnavailableReason": "Max HR unknown: no age or max HR available",
        }
    if bpm_1hz.size == 0:
        return {
            "hrMax": hr_max.as_dict(),
            "timeInZonesS": None,
            "trainingLoad": None,
            "zonesUnavailableReason": "No heart-rate series",
        }
    idx = zone_index(bpm_1hz, hr_max.value)
    seconds = np.bincount(idx, minlength=6) * P3_HR_GRID_S
    trimp = float(sum((seconds[z] / 60.0) * z for z in range(1, 6)))  # Edwards TRIMP
    return {
        "hrMax": hr_max.as_dict(),
        "timeInZonesS": {k: float(seconds[i]) for i, k in enumerate(ZONE_KEYS)},
        "trainingLoad": round(trimp, 1),
        "zonesUnavailableReason": None,
    }
