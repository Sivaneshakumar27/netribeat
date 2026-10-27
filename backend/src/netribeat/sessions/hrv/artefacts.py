"""Artefact correction for RR intervals (design-spec §6, P4)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from netribeat.sessions.hrv.constants import (
    ARTEFACT_THRESHOLD,
    ARTEFACT_WINDOW_BEATS,
    P4_RR_RANGE_MS,
)

F = npt.NDArray[np.float64]


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
