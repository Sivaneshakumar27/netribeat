"""Respiratory rate: HF peak (Hz) × 60, for the session and per minute (P5: 2-minute
windows stepped every minute)."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from netribeat.engine.algo.hrv_features.frequency_domain import (
    BANDS_HZ,
    lomb_band,
    lomb_scargle_psd,
)

F = npt.NDArray[np.float64]

P5_RESP_WINDOW_S, P5_RESP_STEP_S = 120.0, 60.0  # P5: per-minute respiratory rate
RESP_WINDOW_MIN_BEATS = 30


def respiratory_rate(hf_peak_hz: float | None) -> dict[str, Any]:
    return {"value": hf_peak_hz * 60.0 if hf_peak_hz else None, "hfPeakHz": hf_peak_hz}


def respiratory_per_minute(t_s: F, rr: F, duration_s: float) -> list[float | None]:
    """P5 (provisional): HF peak × 60 of each 2-minute window, stepped every minute."""
    out: list[float | None] = []
    start = 0.0
    while start + P5_RESP_WINDOW_S <= duration_s + 1e-9:
        m = (t_s >= start) & (t_s < start + P5_RESP_WINDOW_S)
        if m.sum() >= RESP_WINDOW_MIN_BEATS:
            _, peak = lomb_band(lomb_scargle_psd(t_s[m], rr[m]), *BANDS_HZ["hf"])
            out.append(round(peak * 60.0, 2) if peak else None)
        else:
            out.append(None)
        start += P5_RESP_STEP_S
    return out
