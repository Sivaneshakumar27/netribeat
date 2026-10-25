"""R-peak detection exactly as design-spec §6 states it:
derivative → square → 150 ms moving integration → threshold 0.3 × max → 250 ms
refractory → refine to the raw-signal maximum. No extra filtering is applied (none is
specified)."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from netribeat.analysis.constants import PT_INTEGRATION_S, PT_REFRACTORY_S, PT_THRESHOLD_FRACTION

IntArray = npt.NDArray[np.int64]


def detect_r_peaks(x: npt.NDArray[np.float64], fs: float) -> IntArray:
    n = x.size
    if n < 2 or fs <= 0:
        return np.empty(0, dtype=np.int64)
    derivative = np.diff(x, prepend=x[0])
    squared = derivative * derivative
    w = max(1, round(PT_INTEGRATION_S * fs))
    # Causal (trailing) moving average: mwi[i] = mean(squared[i-w+1 … i]).
    integrated = np.convolve(squared, np.ones(w) / w, mode="full")[:n]
    peak_level = float(integrated.max())
    if peak_level <= 0.0:
        return np.empty(0, dtype=np.int64)
    above = integrated > PT_THRESHOLD_FRACTION * peak_level
    edges = np.diff(above.astype(np.int8), prepend=0, append=0)
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    refractory = round(PT_REFRACTORY_S * fs)
    peaks: list[int] = []
    for s_np, e_np in zip(starts, ends, strict=True):
        s, e = int(s_np), int(e_np)
        # The trailing window lags the QRS by up to w samples: search the raw maximum
        # over [s − w, e).
        lo, hi = max(0, s - w), max(e, s + 1)
        p = lo + int(np.argmax(x[lo:hi]))
        if peaks and p - peaks[-1] < refractory:
            if x[p] > x[peaks[-1]]:
                peaks[-1] = p
            continue
        peaks.append(p)
    return np.asarray(peaks, dtype=np.int64)
