"""RR intervals, artefact correction and signal quality (design-spec §6, P2, P4)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from netribeat.analysis.constants import (
    ARTEFACT_THRESHOLD,
    ARTEFACT_WINDOW_BEATS,
    P4_RR_RANGE_MS,
    QUALITY_MIN_RR,
    QUALITY_POOR_ARTEFACT_PCT,
)
from netribeat.analysis.rpeaks import detect_r_peaks
from netribeat.parsers.base import EcgSegment

F = npt.NDArray[np.float64]


@dataclass(frozen=True)
class BeatSeries:
    t_s: F  # time of each beat (end of its RR interval), seconds from recording start
    rr_ms: F
    peaks_detected: int


def rr_from_ecg(segments: list[EcgSegment], fs: float) -> tuple[BeatSeries, list[np.ndarray]]:
    """Detect R-peaks per segment; RR only between peaks of the same segment (P2)."""
    times: list[F] = []
    rrs: list[F] = []
    detected = 0
    peaks_per_segment: list[np.ndarray] = []
    for seg in segments:
        peaks = detect_r_peaks(seg.samples, fs)
        peaks_per_segment.append(peaks)
        detected += peaks.size
        if peaks.size < 2:
            continue
        t = seg.start_s + peaks / fs
        rrs.append(np.diff(t) * 1000.0)
        times.append(t[1:])
    if not rrs:
        return BeatSeries(np.empty(0), np.empty(0), detected), peaks_per_segment
    return BeatSeries(np.concatenate(times), np.concatenate(rrs), detected), peaks_per_segment


def rr_from_intervals(rr_ms: F) -> BeatSeries:
    return BeatSeries(np.cumsum(rr_ms) / 1000.0, rr_ms.astype(np.float64), int(rr_ms.size))


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


def quality(rr_count: int, artefact_pct: float) -> str:
    if rr_count < QUALITY_MIN_RR:
        return "no_ecg"
    if artefact_pct > QUALITY_POOR_ARTEFACT_PCT:
        return "poor"
    return "good"
