"""Advanced HRV analysis using the definitions of Kubios HRV (Tarvainen et al., Comput.
Methods Programs Biomed. 2014;113:210-220) and the cited primary methods.

Pure NumPy/SciPy, no database. Input: beat times and raw RR intervals of one recording.
Every option has a documented default; see docs/processing.md (Kubios-style HRV).

Definitions confirmed from a Kubios report supplied by the user:
* "log" power = natural logarithm; n.u. = band / (LF + HF) × 100 (= band / (total − VLF))
* pNN50 = NN50 / (number of successive differences) × 100
* SD1 % / SD2 % in the ANS panel = SD1 / (SD1 + SD2) × 100, SD2 / (SD1 + SD2) × 100
* Mean RR, mean HR, min and max HR use the non-detrended series; every other result
  uses the detrended series
* Stress index is reported as √(Baevsky SI)
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt
from scipy import signal, sparse
from scipy.interpolate import CubicSpline
from scipy.linalg import solve_toeplitz
from scipy.sparse.linalg import spsolve

from netribeat.sessions.hrv import artefacts as beats_mod
from netribeat.sessions.hrv import spectral as spec_hrv

F = npt.NDArray[np.float64]

CORRECTION_LEVELS_S = {  # Kubios threshold levels, seconds at 60 bpm (scaled by mean RR)
    "very_low": 0.45,
    "low": 0.35,
    "medium": 0.25,
    "strong": 0.15,
    "very_strong": 0.05,
}
CORRECTIONS = ("none", "spec", *CORRECTION_LEVELS_S)
BANDS = {"vlf": (0.0, 0.04), "lf": (0.04, 0.15), "hf": (0.15, 0.4)}  # Kubios band edges
TRIANGULAR_BIN_MS = 1000.0 / 128.0  # 7.8125 ms (Task Force 1996)
STRESS_BIN_MS = 50.0  # Baevsky
MAX_BEATS_QUADRATIC = 4000  # ApEn/SampEn/RPA are O(N²); larger samples are reported unavailable
MIN_BEATS = 30


@dataclass(frozen=True)
class AdvancedOptions:
    sample_start_s: float = 0.0
    sample_length_s: float | None = 300.0  # None = to the end of the recording
    # Default "low": 0 beats flagged in the clean D1 baseline; catches D1 post-match artefacts.
    correction: str = "low"  # none | spec | very_low | low | medium | strong | very_strong
    detrend: str = "smoothness_priors"  # none | smoothness_priors
    smoothness_lambda: float = 500.0
    interp_hz: float = 4.0
    welch_window_s: float = 256.0
    welch_overlap: float = 0.5
    points_per_hz: int = 300
    ar_order: int = 16
    minmax_hr_beats: int = 5
    entropy_m: int = 2
    entropy_r: float = 0.2  # × SDNN
    dfa_short: tuple[int, int] = (4, 16)
    dfa_long: tuple[int, int] = (16, 64)
    rpa_m: int = 10
    tv_window_s: float = 60.0
    tv_step_s: float = 10.0

    def validated(self) -> AdvancedOptions:
        if self.correction not in CORRECTIONS:
            raise ValueError(f"correction must be one of {', '.join(CORRECTIONS)}")
        if self.detrend not in ("none", "smoothness_priors"):
            raise ValueError("detrend must be none or smoothness_priors")
        if self.sample_start_s < 0 or (
            self.sample_length_s is not None and self.sample_length_s < 30
        ):
            raise ValueError("the sample must start at ≥ 0 s and last ≥ 30 s")
        if not 1 <= self.smoothness_lambda <= 100000:
            raise ValueError("smoothness_lambda must be 1–100000")
        if not 2 <= self.ar_order <= 40:
            raise ValueError("ar_order must be 2–40")
        if not 30 <= self.welch_window_s <= 600:
            raise ValueError("welch_window_s must be 30–600")
        if not 10 <= self.tv_window_s <= 600 or not 1 <= self.tv_step_s <= self.tv_window_s:
            raise ValueError("time-varying window must be 10–600 s with a step ≤ the window")
        return self

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["dfa_short"], d["dfa_long"] = list(self.dfa_short), list(self.dfa_long)
        return d


@dataclass
class AdvancedResult:
    metrics: dict[str, Any]
    series: dict[str, Any] = field(default_factory=dict)


def _r(v: float | None, nd: int = 3) -> float | None:
    if v is None:
        return None
    v = float(v)
    return round(v, nd) if math.isfinite(v) else None


# ---------------------------------------------------------------- preprocessing


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


def smoothness_priors(z: F, lam: float) -> F:
    """Tarvainen et al. 2002: trend = (I + λ² D₂ᵀD₂)⁻¹ z, D₂ the second-difference matrix."""
    n = z.size
    if n < 3:
        return np.full(n, float(np.mean(z)))
    d2 = sparse.diags([1.0, -2.0, 1.0], [0, 1, 2], shape=(n - 2, n))
    a = sparse.identity(n, format="csc") + lam**2 * (d2.T @ d2)
    return np.asarray(spsolve(a.tocsc(), z), dtype=np.float64)


# ---------------------------------------------------------------- time domain


def _histogram(rr: F, width_ms: float) -> tuple[F, npt.NDArray[np.int64]]:
    lo = math.floor(rr.min() / width_ms) * width_ms
    edges = np.arange(lo, rr.max() + width_ms * 1.001, width_ms)
    if edges.size < 2:
        edges = np.array([lo, lo + width_ms])
    counts, edges = np.histogram(rr, bins=edges)
    return edges, counts.astype(np.int64)


def tinn(rr: F) -> float | None:
    """Task Force 1996: base width M − N of the triangle that best fits (least squares)
    the RR histogram (7.8125 ms bins), with its apex at the histogram maximum."""
    edges, d = _histogram(rr, TRIANGULAR_BIN_MS)
    centers = (edges[:-1] + edges[1:]) / 2
    x = int(np.argmax(d))
    y = float(d[x])
    if d.size < 3:
        return None
    best = (math.inf, 0, d.size - 1)
    idx = np.arange(d.size)
    for n_i in range(0, x + 1):
        left = np.zeros(d.size)
        if x > n_i:
            seg = (idx >= n_i) & (idx <= x)
            left[seg] = y * (idx[seg] - n_i) / (x - n_i)
        else:
            left[x] = y
        for m_i in range(x, d.size):
            q = left.copy()
            if m_i > x:
                seg = (idx > x) & (idx <= m_i)
                q[seg] = y * (m_i - idx[seg]) / (m_i - x)
            err = float(np.sum((d - q) ** 2))
            if err < best[0]:
                best = (err, n_i, m_i)
    _, n_b, m_b = best
    return float(centers[m_b] - centers[n_b] + TRIANGULAR_BIN_MS)


def stress_index(rr: F) -> tuple[float | None, dict[str, float]]:
    """Baevsky SI = AMo × 100 % / (2 · Mo · MxDMn), 50 ms bins; returns √SI as Kubios."""
    edges, counts = _histogram(rr, STRESS_BIN_MS)
    k = int(np.argmax(counts))
    mo_s = (edges[k] + edges[k + 1]) / 2 / 1000.0
    amo = 100.0 * counts[k] / rr.size
    mxdmn = (rr.max() - rr.min()) / 1000.0
    if mxdmn <= 0 or mo_s <= 0:
        return None, {}
    si = amo / (2.0 * mo_s * mxdmn)
    return math.sqrt(si), {"modeS": mo_s, "amoPct": amo, "mxdmnS": mxdmn, "baevskySi": si}


def time_domain(raw: F, det: F, opts: AdvancedOptions) -> dict[str, Any]:
    hr_raw = 60000.0 / raw
    k = max(1, opts.minmax_hr_beats)
    smooth = np.convolve(hr_raw, np.ones(k) / k, mode="valid") if hr_raw.size >= k else hr_raw
    d = np.diff(det)
    nn50 = int(np.sum(np.abs(d) > 50.0))
    _, counts = _histogram(det, TRIANGULAR_BIN_MS)
    si, si_parts = stress_index(det)
    return {
        "meanRr": _r(raw.mean(), 1),  # non-detrended
        "meanHr": _r(hr_raw.mean(), 1),  # non-detrended
        "minHr": _r(smooth.min(), 1),  # non-detrended, 5-beat moving average
        "maxHr": _r(smooth.max(), 1),
        "sdHr": _r(np.std(60000.0 / det, ddof=1), 2),
        "sdnn": _r(np.std(det, ddof=1), 2),
        "rmssd": _r(np.sqrt(np.mean(d * d)), 2),
        "nn50": nn50,
        "pnn50": _r(100.0 * nn50 / d.size, 2),
        "triangularIndex": _r(det.size / counts.max(), 2),
        "tinn": _r(tinn(det), 1),
        "stressIndex": _r(si, 2),
        "stressIndexParts": {k_: _r(v, 4) for k_, v in si_parts.items()},
        "beats": int(raw.size),
    }


# ---------------------------------------------------------------- frequency domain


def resample(t: F, rr: F, fs: float) -> tuple[F, F]:
    """Cubic-spline interpolation of the RR series onto an even grid (Kubios: 4 Hz)."""
    grid = np.arange(t[0], t[-1], 1.0 / fs)
    return grid, CubicSpline(t, rr)(grid)


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
            "peakHz": _r(peak, 4),
            "power": _r(p, 1),
            "logPower": _r(math.log(p), 3) if p > 0 else None,
        }
    total = sum(powers.values())
    lfhf = powers["lf"] + powers["hf"]
    for name in BANDS:
        out[name]["powerPct"] = _r(100.0 * powers[name] / total, 2) if total else None
        out[name]["powerNu"] = (
            _r(100.0 * powers[name] / lfhf, 2) if lfhf and name != "vlf" else None
        )
    return {
        "bands": out,
        "totalPower": _r(total, 1),
        "logTotalPower": _r(math.log(total), 3) if total > 0 else None,
        "lfHf": _r(powers["lf"] / powers["hf"], 3) if powers["hf"] else None,
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


def frequency_domain(t: F, det: F, opts: AdvancedOptions) -> tuple[dict[str, Any], dict[str, Any]]:
    _, x = resample(t, det, opts.interp_hz)
    fw, pw = welch_psd(x, opts)
    fa_fine, pa_fine = ar_psd(x, opts, AR_INTEGRATION_POINTS_PER_HZ)
    step = max(1, AR_INTEGRATION_POINTS_PER_HZ // opts.points_per_hz)
    fa, pa = fa_fine[::step], pa_fine[::step]  # plotting resolution
    lomb = spec_hrv.frequency_domain(t, det)
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


# ---------------------------------------------------------------- nonlinear


def _count_within(x: F, m: int, r: float, *, self_match: bool) -> F:
    """For each template of length m, the number of templates within Chebyshev r."""
    n = x.size - m + 1
    emb = np.lib.stride_tricks.sliding_window_view(x, m)[:n]
    counts = np.zeros(n)
    for start in range(0, n, 512):  # blockwise: memory O(512·N)
        block = emb[start : start + 512]
        dist = np.max(np.abs(block[:, None, :] - emb[None, :, :]), axis=2)
        counts[start : start + 512] = np.sum(dist <= r, axis=1)
    if not self_match:
        counts -= 1
    return counts


def apen(x: F, m: int, r: float) -> float:
    """Pincus 1991 (self-matches included)."""

    def phi(mm: int) -> float:
        c = _count_within(x, mm, r, self_match=True) / (x.size - mm + 1)
        return float(np.mean(np.log(c)))

    return phi(m) - phi(m + 1)


def sampen(x: F, m: int, r: float) -> float | None:
    """Richman & Moorman 2000 (self-matches excluded; N − m templates for both lengths)."""
    n = x.size
    b = _count_within(x[: n - 1], m, r, self_match=False).sum()
    a = _count_within(x, m + 1, r, self_match=False).sum()
    return None if a == 0 or b == 0 else float(-math.log(a / b))


def dfa(x: F, scales: tuple[int, int]) -> tuple[float | None, list[list[float]]]:
    """Peng et al. 1995: integrated, box-wise linearly detrended fluctuation F(n);
    α = slope of log10 F(n) vs log10 n over the scale range (inclusive)."""
    y = np.cumsum(x - x.mean())
    pts: list[list[float]] = []
    for n in range(scales[0], scales[1] + 1):
        boxes = y.size // n
        if boxes < 2:
            break
        seg = y[: boxes * n].reshape(boxes, n)
        k = np.arange(n)
        coef = np.polyfit(k, seg.T, 1)
        trend = np.outer(coef[0], k) + coef[1][:, None]
        f = math.sqrt(float(np.mean((seg - trend) ** 2)))
        if f > 0:
            pts.append([math.log10(n), math.log10(f)])
    if len(pts) < 3:
        return None, pts
    arr = np.asarray(pts)
    return float(np.polyfit(arr[:, 0], arr[:, 1], 1)[0]), pts


def recurrence(x: F, m: int, sdnn: float) -> dict[str, float | None]:
    """Recurrence plot (Kubios: embedding m = 10, τ = 1, threshold r = √m · SDNN,
    Euclidean distance): REC, DET, mean / max diagonal line length, Shannon entropy."""
    emb = np.lib.stride_tricks.sliding_window_view(x, m)
    n = emb.shape[0]
    if n < 10:
        return {k: None for k in ("rec", "det", "lmean", "lmax", "shanEn")}
    r = math.sqrt(m) * sdnn
    sq = np.sum(emb * emb, axis=1)
    rp = (sq[:, None] + sq[None, :] - 2 * emb @ emb.T) <= r * r
    rec = float(rp.sum()) / (n * n)
    lengths: list[int] = []
    for k in range(1, n):  # upper diagonals (symmetric), main diagonal excluded
        diag = np.diagonal(rp, k).astype(np.int8)
        edges = np.diff(np.concatenate([[0], diag, [0]]))
        runs = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
        lengths.extend(int(v) for v in runs if v >= 2)
    off_points = (rp.sum() - n) / 2
    det = (sum(lengths) / off_points) if off_points else 0.0
    if lengths:
        counts = np.bincount(lengths)[2:]
        p = counts[counts > 0] / counts.sum()
        shan = float(-np.sum(p * np.log(p)))
    else:
        shan = 0.0
    return {
        "rec": _r(100 * rec, 2),
        "det": _r(100 * det, 2),
        "lmean": _r(np.mean(lengths), 2) if lengths else None,
        "lmax": max(lengths) if lengths else None,
        "shanEn": _r(shan, 3),
    }


def nonlinear(
    det: F, opts: AdvancedOptions
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    unavailable: dict[str, str] = {}
    sdnn = float(np.std(det, ddof=1))
    pc = spec_hrv.poincare(det)
    sd1, sd2 = pc["sd1"], pc["sd2"]
    out: dict[str, Any] = {
        "sd1": _r(sd1, 2),
        "sd2": _r(sd2, 2),
        "sd2Sd1": _r(sd2 / sd1, 3) if sd1 and sd2 else None,
        "apen": None,
        "sampen": None,
        "dfaAlpha1": None,
        "dfaAlpha2": None,
        "recurrence": None,
    }
    if det.size <= MAX_BEATS_QUADRATIC:
        r = opts.entropy_r * sdnn
        out["apen"] = _r(apen(det, opts.entropy_m, r), 3)
        out["sampen"] = _r(sampen(det, opts.entropy_m, r), 3)
        out["recurrence"] = recurrence(det, opts.rpa_m, sdnn)
    else:
        reason = (
            f"Not computed for samples over {MAX_BEATS_QUADRATIC} beats; choose a shorter sample"
        )
        unavailable.update(apen=reason, sampen=reason, recurrence=reason)
    a1, p1 = dfa(det, opts.dfa_short)
    a2, p2 = dfa(det, opts.dfa_long)
    out["dfaAlpha1"], out["dfaAlpha2"] = _r(a1, 3), _r(a2, 3)
    if a2 is None:
        unavailable["dfaAlpha2"] = f"Needs at least {2 * opts.dfa_long[1]} beats"
    return out, {"dfa": {"short": p1, "long": p2}}, unavailable


# ---------------------------------------------------------------- time-varying


def time_varying(t: F, rr: F, opts: AdvancedOptions) -> dict[str, list[float | None]]:
    start, end = float(t[0]), float(t[-1])
    rows: dict[str, list[float | None]] = {
        "tS": [],
        "meanHr": [],
        "rmssd": [],
        "sdnn": [],
        "sd1": [],
        "stressIndex": [],
    }
    s = start
    while s + opts.tv_window_s <= end + 1e-9:
        m = (t >= s) & (t < s + opts.tv_window_s)
        w = rr[m]
        rows["tS"].append(round(s + opts.tv_window_s / 2, 1))
        if w.size >= 10:
            d = np.diff(w)
            rows["meanHr"].append(_r(np.mean(60000.0 / w), 1))
            rows["rmssd"].append(_r(np.sqrt(np.mean(d * d)), 1))
            rows["sdnn"].append(_r(np.std(w, ddof=1), 1))
            rows["sd1"].append(_r(np.std(d, ddof=1) / math.sqrt(2), 1))
            rows["stressIndex"].append(_r(stress_index(w)[0], 2))
        else:
            for k in ("meanHr", "rmssd", "sdnn", "sd1", "stressIndex"):
                rows[k].append(None)
        s += opts.tv_step_s
    return rows


# ---------------------------------------------------------------- entry point


def analyse_advanced(beat_t: F, rr_raw: F, opts: AdvancedOptions) -> AdvancedResult:
    opts = opts.validated()
    t_all, rr_all = np.asarray(beat_t, float), np.asarray(rr_raw, float)
    meta: dict[str, Any] = {"options": opts.as_dict(), "warnings": [], "unavailable": {}}
    if rr_all.size < MIN_BEATS:
        meta["unavailable"]["all"] = (
            f"At least {MIN_BEATS} RR intervals are needed (found {rr_all.size})"
        )
        return AdvancedResult(meta)

    # Correction is applied to the whole recording (context for local medians), then the
    # sample is cut out.
    if opts.correction == "none":
        rr_c, flags = rr_all.copy(), np.zeros(rr_all.size, dtype=bool)
    elif opts.correction == "spec":
        corr = beats_mod.correct_artefacts(rr_all)
        rr_c, flags = corr.corrected, corr.flags
    else:
        rr_c, flags = threshold_correction(t_all, rr_all, opts.correction)

    t0 = t_all[0] - rr_all[0] / 1000.0  # start of the recording
    s0 = t0 + opts.sample_start_s
    s1 = s0 + opts.sample_length_s if opts.sample_length_s else t_all[-1] + 1e-9
    m = (t_all > s0) & (t_all <= s1)
    t, raw = t_all[m], rr_c[m]
    meta["sample"] = {
        "startS": _r(opts.sample_start_s, 1),
        "lengthS": _r(float(min(s1, t_all[-1]) - s0), 1),
        "measurementLengthS": _r(float(t_all[-1] - t0), 1),
        "beats": int(raw.size),
        "beatsCorrected": int(flags[m].sum()),
        "beatsCorrectedPct": _r(100.0 * flags[m].sum() / max(1, raw.size), 2),
    }
    if raw.size < MIN_BEATS:
        meta["unavailable"]["all"] = (
            f"The selected sample has {raw.size} beats; at least {MIN_BEATS} are needed"
        )
        return AdvancedResult(meta)
    if opts.sample_length_s and s1 > t_all[-1] + 1:
        meta["warnings"].append("The selected sample extends past the end of the recording")

    trend = (
        smoothness_priors(raw, opts.smoothness_lambda)
        if opts.detrend != "none"
        else np.full(raw.size, raw.mean())
    )
    det = raw - trend + raw.mean()  # detrended, mean restored (histogram indices need RR scale)

    td = time_domain(raw, det, opts)
    fd, fd_series = frequency_domain(t, det, opts)
    nl, nl_series, nl_unavail = nonlinear(det, opts)
    meta["unavailable"].update(nl_unavail)
    sd1, sd2 = nl["sd1"], nl["sd2"]
    ans = {
        "pns": {
            "meanRr": td["meanRr"],
            "rmssd": td["rmssd"],
            "sd1Pct": _r(100 * sd1 / (sd1 + sd2), 1) if sd1 and sd2 else None,
        },
        "sns": {
            "meanHr": td["meanHr"],
            "stressIndex": td["stressIndex"],
            "sd2Pct": _r(100 * sd2 / (sd1 + sd2), 1) if sd1 and sd2 else None,
        },
        "pnsIndex": None,
        "snsIndex": None,
        "indexUnavailableReason": (
            "PNS/SNS indexes compare these values with Kubios' normative population values, "
            "which haven't been provided; the component values are shown"
        ),
    }
    if meta["sample"]["lengthS"] and meta["sample"]["lengthS"] < 120:
        meta["warnings"].append("Samples shorter than 2 minutes give unreliable LF power")
    if meta["sample"]["lengthS"] and meta["sample"]["lengthS"] < 250:
        meta["warnings"].append("VLF power needs longer samples; interpret it with care")

    metrics = {**meta, "timeDomain": td, "frequencyDomain": fd, "nonlinear": nl, "ans": ans}
    edges, counts = _histogram(det, TRIANGULAR_BIN_MS)
    series = {
        "tachogram": {
            "tS": np.round(t_all, 3).tolist(),
            "rrMs": np.round(rr_all, 1).tolist(),
            "flags": np.flatnonzero(flags).tolist(),
        },
        "sample": {
            "tS": np.round(t, 3).tolist(),
            "rrMs": np.round(raw, 1).tolist(),
            "trendMs": np.round(trend, 2).tolist(),
            "detrendedMs": np.round(det - det.mean(), 2).tolist(),
        },
        "histogram": {"edgesMs": np.round(edges, 3).tolist(), "counts": counts.tolist()},
        "spectrum": fd_series,
        **nl_series,
        "timeVarying": time_varying(t_all, rr_c, opts),
    }
    return AdvancedResult(metrics, series)
