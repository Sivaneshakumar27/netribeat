"""HRV time domain: all statistics on the RR series, in one file.

* `basic_time_domain` — design-spec §6 (first 5 min, corrected RR): mean RR / HR, SDNN, RMSSD,
  pNNI20 / pNNI50.
* `kubios_time_domain` — Kubios definitions: + SD HR, min / max HR (5-beat average), NN50, pNN50,
  RR triangular index, TINN, stress index (√ Baevsky SI).
* `time_varying` — mean HR, RMSSD, SDNN, SD1 and stress index in moving windows.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from netribeat.engine.algo.common import rounded

if TYPE_CHECKING:
    from netribeat.metrics.hrv_metrics import AdvancedOptions

F = npt.NDArray[np.float64]

PNNI_THRESHOLDS_MS = (20.0, 50.0)
TRIANGULAR_BIN_MS = 1000.0 / 128.0  # 7.8125 ms (Task Force 1996)
STRESS_BIN_MS = 50.0  # Baevsky


def basic_time_domain(rr: F) -> dict[str, Any]:
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


def rr_histogram(rr: F, width_ms: float) -> tuple[F, npt.NDArray[np.int64]]:
    lo = math.floor(rr.min() / width_ms) * width_ms
    edges = np.arange(lo, rr.max() + width_ms * 1.001, width_ms)
    if edges.size < 2:
        edges = np.array([lo, lo + width_ms])
    counts, edges = np.histogram(rr, bins=edges)
    return edges, counts.astype(np.int64)


def tinn(rr: F) -> float | None:
    """Task Force 1996: base width M − N of the triangle that best fits (least squares)
    the RR histogram (7.8125 ms bins), with its apex at the histogram maximum."""
    edges, d = rr_histogram(rr, TRIANGULAR_BIN_MS)
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
    edges, counts = rr_histogram(rr, STRESS_BIN_MS)
    k = int(np.argmax(counts))
    mo_s = (edges[k] + edges[k + 1]) / 2 / 1000.0
    amo = 100.0 * counts[k] / rr.size
    mxdmn = (rr.max() - rr.min()) / 1000.0
    if mxdmn <= 0 or mo_s <= 0:
        return None, {}
    si = amo / (2.0 * mo_s * mxdmn)
    return math.sqrt(si), {"modeS": mo_s, "amoPct": amo, "mxdmnS": mxdmn, "baevskySi": si}


def kubios_time_domain(raw: F, det: F, opts: AdvancedOptions) -> dict[str, Any]:
    hr_raw = 60000.0 / raw
    k = max(1, opts.minmax_hr_beats)
    smooth = np.convolve(hr_raw, np.ones(k) / k, mode="valid") if hr_raw.size >= k else hr_raw
    d = np.diff(det)
    nn50 = int(np.sum(np.abs(d) > 50.0))
    _, counts = rr_histogram(det, TRIANGULAR_BIN_MS)
    si, si_parts = stress_index(det)
    return {
        "meanRr": rounded(raw.mean(), 1),  # non-detrended
        "meanHr": rounded(hr_raw.mean(), 1),  # non-detrended
        "minHr": rounded(smooth.min(), 1),  # non-detrended, 5-beat moving average
        "maxHr": rounded(smooth.max(), 1),
        "sdHr": rounded(np.std(60000.0 / det, ddof=1), 2),
        "sdnn": rounded(np.std(det, ddof=1), 2),
        "rmssd": rounded(np.sqrt(np.mean(d * d)), 2),
        "nn50": nn50,
        "pnn50": rounded(100.0 * nn50 / d.size, 2),
        "triangularIndex": rounded(det.size / counts.max(), 2),
        "tinn": rounded(tinn(det), 1),
        "stressIndex": rounded(si, 2),
        "stressIndexParts": {k_: rounded(v, 4) for k_, v in si_parts.items()},
        "beats": int(raw.size),
    }


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
            rows["meanHr"].append(rounded(np.mean(60000.0 / w), 1))
            rows["rmssd"].append(rounded(np.sqrt(np.mean(d * d)), 1))
            rows["sdnn"].append(rounded(np.std(w, ddof=1), 1))
            rows["sd1"].append(rounded(np.std(d, ddof=1) / math.sqrt(2), 1))
            rows["stressIndex"].append(rounded(stress_index(w)[0], 2))
        else:
            for k in ("meanHr", "rmssd", "sdnn", "sd1", "stressIndex"):
                rows[k].append(None)
        s += opts.tv_step_s
    return rows
