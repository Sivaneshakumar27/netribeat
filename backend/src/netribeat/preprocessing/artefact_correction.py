"""Artefact detection and correction for RR intervals.

* `correct_artefacts`: design-spec §6 rule — a beat > 20 % from the median of its 11-beat window,
  or outside 250–2500 ms (P4), is replaced by that median.
* `threshold_correction`: Kubios threshold levels (very low … very strong), replaced by
  cubic-spline interpolation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.interpolate import CubicSpline

F = npt.NDArray[np.float64]

ARTEFACT_WINDOW_BEATS = 11  # local median window (centred; truncated at the ends)
ARTEFACT_THRESHOLD = 0.20  # > 20 % from the local median
P4_RR_RANGE_MS = (250.0, 2500.0)  # P4: RR outside → artefact, replaced like others

CORRECTION_LEVELS_S = {  # Kubios threshold levels, seconds at 60 bpm (scaled by mean RR)
    "very_low": 0.45,
    "low": 0.35,
    "medium": 0.25,
    "strong": 0.15,
    "very_strong": 0.05,
}
CORRECTIONS = ("none", "spec", *CORRECTION_LEVELS_S)


@dataclass(frozen=True)
class Correction:
    corrected: F
    flags: npt.NDArray[np.bool_]

    @property
    def count(self) -> int:
        return int(self.flags.sum())

    @property
    def pct(self) -> float:
        return 100.0 * self.count / self.flags.size if self.flags.size else 0.0


def correct_artefacts(rr: F) -> Correction:
    """A beat more than 20 % from the median of its local 11-beat window (centred,
    truncated at the ends) is flagged and replaced by that median. P4: RR outside
    250–2500 ms is flagged and replaced the same way."""
    n = rr.size
    half = ARTEFACT_WINDOW_BEATS // 2
    corrected = rr.astype(np.float64).copy()
    flags = np.zeros(n, dtype=bool)
    lo_ms, hi_ms = P4_RR_RANGE_MS
    for i in range(n):
        med = float(np.median(rr[max(0, i - half) : min(n, i + half + 1)]))
        out_of_range = rr[i] < lo_ms or rr[i] > hi_ms
        if out_of_range or abs(rr[i] - med) > ARTEFACT_THRESHOLD * med:
            flags[i] = True
            corrected[i] = med
    return Correction(corrected, flags)


def threshold_correction(t: F, rr: F, level: str) -> tuple[F, npt.NDArray[np.bool_]]:
    """Kubios threshold-based correction: a beat differing from the local median (11
    beats) by more than the level's threshold (seconds at 60 bpm, scaled by the mean RR)
    is replaced by cubic-spline interpolation through the remaining beats."""
    thr_ms = CORRECTION_LEVELS_S[level] * 1000.0 * (float(np.mean(rr)) / 1000.0)
    n, half = rr.size, 5
    med = np.array([np.median(rr[max(0, i - half) : min(n, i + half + 1)]) for i in range(n)])
    flags = np.abs(rr - med) > thr_ms
    out = rr.copy()
    good = ~flags
    if flags.any() and good.sum() >= 4:
        out[flags] = CubicSpline(t[good], rr[good])(t[flags])
    elif flags.any():
        out[flags] = med[flags]
    return out, flags
