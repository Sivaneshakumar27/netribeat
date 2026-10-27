"""HRV nonlinear analysis, in one file: Poincaré SD1/SD2, approximate and sample entropy,
detrended fluctuation analysis (α1, α2) and recurrence quantification."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

from netribeat.engine.algo.common import rounded

if TYPE_CHECKING:
    from netribeat.metrics.hrv_metrics import AdvancedOptions

F = npt.NDArray[np.float64]


def poincare(rr: F) -> dict[str, Any]:
    sd1 = float(np.std(np.diff(rr), ddof=1) / np.sqrt(2.0))
    sdnn = float(np.std(rr, ddof=1))
    inner = 2.0 * sdnn * sdnn - sd1 * sd1
    sd2 = float(np.sqrt(inner)) if inner > 0 else None
    return {"sd1": sd1, "sd2": sd2, "sd1Sd2": (sd1 / sd2) if sd2 else None}


MAX_BEATS_QUADRATIC = 4000  # ApEn/SampEn/RPA are O(N²); larger samples are reported unavailable


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
        "rec": rounded(100 * rec, 2),
        "det": rounded(100 * det, 2),
        "lmean": rounded(np.mean(lengths), 2) if lengths else None,
        "lmax": max(lengths) if lengths else None,
        "shanEn": rounded(shan, 3),
    }


def nonlinear(
    det: F, opts: AdvancedOptions
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    unavailable: dict[str, str] = {}
    sdnn = float(np.std(det, ddof=1))
    pc = poincare(det)
    sd1, sd2 = pc["sd1"], pc["sd2"]
    out: dict[str, Any] = {
        "sd1": rounded(sd1, 2),
        "sd2": rounded(sd2, 2),
        "sd2Sd1": rounded(sd2 / sd1, 3) if sd1 and sd2 else None,
        "apen": None,
        "sampen": None,
        "dfaAlpha1": None,
        "dfaAlpha2": None,
        "recurrence": None,
    }
    if det.size <= MAX_BEATS_QUADRATIC:
        r = opts.entropy_r * sdnn
        out["apen"] = rounded(apen(det, opts.entropy_m, r), 3)
        out["sampen"] = rounded(sampen(det, opts.entropy_m, r), 3)
        out["recurrence"] = recurrence(det, opts.rpa_m, sdnn)
    else:
        reason = (
            f"Not computed for samples over {MAX_BEATS_QUADRATIC} beats; choose a shorter sample"
        )
        unavailable.update(apen=reason, sampen=reason, recurrence=reason)
    a1, p1 = dfa(det, opts.dfa_short)
    a2, p2 = dfa(det, opts.dfa_long)
    out["dfaAlpha1"], out["dfaAlpha2"] = rounded(a1, 3), rounded(a2, 3)
    if a2 is None:
        unavailable["dfaAlpha2"] = f"Needs at least {2 * opts.dfa_long[1]} beats"
    return out, {"dfa": {"short": p1, "long": p2}}, unavailable
