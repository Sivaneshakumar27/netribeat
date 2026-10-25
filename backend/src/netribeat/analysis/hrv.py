"""HRV: time domain, Lomb–Scargle frequency domain, Poincaré, respiratory rate
(design-spec §6) and the P5 per-minute respiratory series."""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from scipy.signal import lombscargle

from netribeat.analysis.constants import (
    BANDS_HZ,
    MOVEMENT_LOAD_DIVISOR,
    P5_RESP_STEP_S,
    P5_RESP_WINDOW_S,
    PNNI_THRESHOLDS_MS,
    PSD_F_MAX,
    PSD_F_MIN,
    PSD_F_STEP,
    RESP_WINDOW_MIN_BEATS,
)

F = npt.NDArray[np.float64]
FREQS = np.round(np.arange(PSD_F_MIN, PSD_F_MAX + PSD_F_STEP / 2, PSD_F_STEP), 6)


def time_domain(rr: F) -> dict[str, Any]:
    d = np.diff(rr)
    p20, p50 = (100.0 * float(np.mean(np.abs(d) > t)) for t in PNNI_THRESHOLDS_MS)
    return {
        "meanRr": float(np.mean(rr)),
        "meanHr": float(np.mean(60000.0 / rr)),
        "sdnn": float(np.std(rr, ddof=1)),  # sample SD
        "rmssd": float(np.sqrt(np.mean(d * d))),
        "pnni20": p20,
        "pnni50": p50,
        "beats": int(rr.size),
    }


def psd(t_s: F, rr: F) -> F:
    """Lomb–Scargle over 0.002–0.5 Hz in 0.002 Hz steps, scaled so Σ P·Δf = RR variance."""
    x = rr - rr.mean()
    raw = lombscargle(t_s, x, 2.0 * np.pi * FREQS)
    area = float(raw.sum() * PSD_F_STEP)
    variance = float(np.var(rr, ddof=1))
    if area <= 0.0:
        return np.zeros_like(FREQS)
    return np.asarray(raw * (variance / area), dtype=np.float64)


def _band(power: F, lo: float, hi: float) -> tuple[float, float | None]:
    mask = (lo <= FREQS) & (hi > FREQS)
    p = float(power[mask].sum() * PSD_F_STEP)
    if not mask.any() or p <= 0.0:
        return 0.0, None
    return p, float(FREQS[mask][int(np.argmax(power[mask]))])


def frequency_domain(t_s: F, rr: F) -> dict[str, Any]:
    power = psd(t_s, rr)
    raw = {k: _band(power, lo, hi) for k, (lo, hi) in BANDS_HZ.items()}
    total = sum(p for p, _ in raw.values())
    lf, hf = raw["lf"][0], raw["hf"][0]
    bands = {}
    for k, (p, peak) in raw.items():
        bands[k] = {
            "rangeHz": list(BANDS_HZ[k]),
            "peakHz": peak,
            "power": p,
            "powerPct": 100.0 * p / total if total else None,
            "powerNu": (100.0 * p / (lf + hf) if (lf + hf) else None)
            if k in ("lf", "hf")
            else None,
        }
    return {
        "freqs": FREQS.tolist(),
        "power": power.tolist(),
        "bands": bands,
        "totalPower": total,  # VLF + LF + HF (ms²)
        "lfHf": (lf / hf) if hf else None,
    }


def poincare(rr: F) -> dict[str, Any]:
    sd1 = float(np.std(np.diff(rr), ddof=1) / np.sqrt(2.0))
    sdnn = float(np.std(rr, ddof=1))
    inner = 2.0 * sdnn * sdnn - sd1 * sd1
    sd2 = float(np.sqrt(inner)) if inner > 0 else None
    return {"sd1": sd1, "sd2": sd2, "sd1Sd2": (sd1 / sd2) if sd2 else None}


def respiratory_rate(hf_peak_hz: float | None) -> dict[str, Any]:
    return {"value": hf_peak_hz * 60.0 if hf_peak_hz else None, "hfPeakHz": hf_peak_hz}


def respiratory_per_minute(t_s: F, rr: F, duration_s: float) -> list[float | None]:
    """P5 (provisional): HF peak × 60 of each 2-minute window, stepped every minute."""
    out: list[float | None] = []
    start = 0.0
    while start + P5_RESP_WINDOW_S <= duration_s + 1e-9:
        m = (t_s >= start) & (t_s < start + P5_RESP_WINDOW_S)
        if m.sum() >= RESP_WINDOW_MIN_BEATS:
            _, peak = _band(psd(t_s[m], rr[m]), *BANDS_HZ["hf"])
            out.append(round(peak * 60.0, 2) if peak else None)
        else:
            out.append(None)
        start += P5_RESP_STEP_S
    return out


def movement_load(x: F, y: F, z: F) -> float:
    """design-spec §6: Σ √(Δx² + Δy² + Δz²) / 100 over tri-axial acceleration in g (AU).
    None of the supported input formats carries acceleration yet."""

    return float(
        np.sum(np.sqrt(np.diff(x) ** 2 + np.diff(y) ** 2 + np.diff(z) ** 2)) / MOVEMENT_LOAD_DIVISOR
    )
