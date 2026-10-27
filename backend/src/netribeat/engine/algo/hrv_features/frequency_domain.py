"""HRV frequency domain: every spectrum and band power, in one file.

* Lomb–Scargle (design-spec §6) — 0.002–0.5 Hz, scaled so Σ P·Δf = RR variance; bands
  VLF 0.0033–0.04, LF 0.04–0.15, HF 0.15–0.4 Hz.
* Kubios — RR resampled at 4 Hz, Welch FFT (Hann, 256 s, 50 % overlap) and Yule–Walker AR
  (order 16); per band peak Hz, power (ms²), ln power, %, n.u.; total and LF/HF.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt
from scipy import signal
from scipy.linalg import solve_toeplitz
from scipy.signal import lombscargle

from netribeat.engine.algo.hrv_features.time_domain import rounded
from netribeat.preprocessing.detrending import resample

if TYPE_CHECKING:
    from netribeat.engine.algo.hrv_features.hrv_analysis import AdvancedOptions

F = npt.NDArray[np.float64]

PSD_F_MIN, PSD_F_MAX, PSD_F_STEP = 0.002, 0.5, 0.002
BANDS_HZ = {"vlf": (0.0033, 0.04), "lf": (0.04, 0.15), "hf": (0.15, 0.4)}
FREQS = np.round(np.arange(PSD_F_MIN, PSD_F_MAX + PSD_F_STEP / 2, PSD_F_STEP), 6)
BANDS = {"vlf": (0.0, 0.04), "lf": (0.04, 0.15), "hf": (0.15, 0.4)}  # Kubios band edges


# ---------------------------------------------------------------- Lomb–Scargle (design-spec §6)


def lomb_scargle_psd(t_s: F, rr: F) -> F:
    """Lomb–Scargle over 0.002–0.5 Hz in 0.002 Hz steps, scaled so Σ P·Δf = RR variance."""
    x = rr - rr.mean()
    raw = lombscargle(t_s, x, 2.0 * np.pi * FREQS)
    area = float(raw.sum() * PSD_F_STEP)
    variance = float(np.var(rr, ddof=1))
    if area <= 0.0:
        return np.zeros_like(FREQS)
    return np.asarray(raw * (variance / area), dtype=np.float64)


def lomb_band(power: F, lo: float, hi: float) -> tuple[float, float | None]:
    mask = (lo <= FREQS) & (hi > FREQS)
    p = float(power[mask].sum() * PSD_F_STEP)
    if not mask.any() or p <= 0.0:
        return 0.0, None
    return p, float(FREQS[mask][int(np.argmax(power[mask]))])


def lomb_scargle_frequency_domain(t_s: F, rr: F) -> dict[str, Any]:
    power = lomb_scargle_psd(t_s, rr)
    raw = {k: lomb_band(power, lo, hi) for k, (lo, hi) in BANDS_HZ.items()}
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


# ---------------------------------------------------------------- Kubios: Welch FFT and AR


def _bands(freqs: F, psd: F) -> dict[str, Any]:
    out: dict[str, Any] = {}
    powers = {}
    for name, (lo, hi) in BANDS.items():
        m = (freqs >= lo) & (freqs < hi) if name != "hf" else (freqs >= lo) & (freqs <= hi)
        p = float(np.trapezoid(psd[m], freqs[m])) if m.sum() > 1 else 0.0
        peak = float(freqs[m][int(np.argmax(psd[m]))]) if m.any() and p > 0 else None
        powers[name] = p
        out[name] = {
            "rangeHz": [lo, hi],
            "peakHz": rounded(peak, 4),
            "power": rounded(p, 1),
            "logPower": rounded(math.log(p), 3) if p > 0 else None,
        }
    total = sum(powers.values())
    lfhf = powers["lf"] + powers["hf"]
    for name in BANDS:
        out[name]["powerPct"] = rounded(100.0 * powers[name] / total, 2) if total else None
        out[name]["powerNu"] = (
            rounded(100.0 * powers[name] / lfhf, 2) if lfhf and name != "vlf" else None
        )
    return {
        "bands": out,
        "totalPower": rounded(total, 1),
        "logTotalPower": rounded(math.log(total), 3) if total > 0 else None,
        "lfHf": rounded(powers["lf"] / powers["hf"], 3) if powers["hf"] else None,
    }


def welch_psd(x: F, opts: AdvancedOptions) -> tuple[F, F]:
    fs = opts.interp_hz
    nper = min(x.size, round(opts.welch_window_s * fs))
    nfft = max(nper, round(fs * opts.points_per_hz))
    f, p = signal.welch(
        x - x.mean(),
        fs=fs,
        window="hann",
        nperseg=nper,
        noverlap=round(nper * opts.welch_overlap),
        nfft=nfft,
        detrend="constant",
        scaling="density",
    )
    return np.asarray(f), np.asarray(p)


AR_INTEGRATION_POINTS_PER_HZ = 10000  # AR peaks can be very narrow; integrate band powers finely


def ar_psd(x: F, opts: AdvancedOptions, points_per_hz: int | None = None) -> tuple[F, F]:
    """Yule–Walker AR(p) spectrum; one-sided, integrates to the series variance."""
    fs, p = opts.interp_hz, opts.ar_order
    x = x - x.mean()
    n = x.size
    ac = np.array([np.dot(x[: n - k], x[k:]) / n for k in range(p + 1)])
    a = solve_toeplitz(ac[:p], ac[1 : p + 1])
    sigma2 = float(ac[0] - np.dot(a, ac[1 : p + 1]))
    freqs = np.arange(0.0, fs / 2 + 1e-12, 1.0 / (points_per_hz or opts.points_per_hz))
    z = np.exp(-2j * np.pi * np.outer(freqs, np.arange(1, p + 1)) / fs)
    denom = np.abs(1.0 - z @ a) ** 2
    return freqs, 2.0 * sigma2 / (fs * denom)


def kubios_frequency_domain(
    t: F, det: F, opts: AdvancedOptions
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, x = resample(t, det, opts.interp_hz)
    fw, pw = welch_psd(x, opts)
    fa_fine, pa_fine = ar_psd(x, opts, AR_INTEGRATION_POINTS_PER_HZ)
    step = max(1, AR_INTEGRATION_POINTS_PER_HZ // opts.points_per_hz)
    fa, pa = fa_fine[::step], pa_fine[::step]  # plotting resolution
    lomb = lomb_scargle_frequency_domain(t, det)
    keep_w, keep_a = fw <= 0.5, fa <= 0.5
    metrics = {
        "fft": _bands(fw, pw),
        "ar": _bands(fa_fine, pa_fine),
        "lomb": {"bands": lomb["bands"], "totalPower": lomb["totalPower"], "lfHf": lomb["lfHf"]},
        "interpolationHz": opts.interp_hz,
    }
    series = {
        "fft": {
            "freqs": np.round(fw[keep_w], 5).tolist(),
            "power": np.round(pw[keep_w], 4).tolist(),
        },
        "ar": {
            "freqs": np.round(fa[keep_a], 5).tolist(),
            "power": np.round(pa[keep_a], 4).tolist(),
        },
        "lomb": {"freqs": lomb["freqs"], "power": [round(v, 4) for v in lomb["power"]]},
    }
    return metrics, series
