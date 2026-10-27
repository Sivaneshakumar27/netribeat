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

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from netribeat.engine.algo.hrv_td_fd_nl.frequency_domain import kubios_frequency_domain
from netribeat.engine.algo.hrv_td_fd_nl.nonlinear import nonlinear
from netribeat.engine.algo.hrv_td_fd_nl.time_domain import (
    TRIANGULAR_BIN_MS,
    kubios_time_domain,
    rounded,
    rr_histogram,
    time_varying,
)
from netribeat.preprocessing.artefact_correction import (
    CORRECTIONS,
    correct_artefacts,
    threshold_correction,
)
from netribeat.preprocessing.detrending import smoothness_priors

F = npt.NDArray[np.float64]

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
        corr = correct_artefacts(rr_all)
        rr_c, flags = corr.corrected, corr.flags
    else:
        rr_c, flags = threshold_correction(t_all, rr_all, opts.correction)

    t0 = t_all[0] - rr_all[0] / 1000.0  # start of the recording
    s0 = t0 + opts.sample_start_s
    s1 = s0 + opts.sample_length_s if opts.sample_length_s else t_all[-1] + 1e-9
    m = (t_all > s0) & (t_all <= s1)
    t, raw = t_all[m], rr_c[m]
    meta["sample"] = {
        "startS": rounded(opts.sample_start_s, 1),
        "lengthS": rounded(float(min(s1, t_all[-1]) - s0), 1),
        "measurementLengthS": rounded(float(t_all[-1] - t0), 1),
        "beats": int(raw.size),
        "beatsCorrected": int(flags[m].sum()),
        "beatsCorrectedPct": rounded(100.0 * flags[m].sum() / max(1, raw.size), 2),
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

    td = kubios_time_domain(raw, det, opts)
    fd, fd_series = kubios_frequency_domain(t, det, opts)
    nl, nl_series, nl_unavail = nonlinear(det, opts)
    meta["unavailable"].update(nl_unavail)
    sd1, sd2 = nl["sd1"], nl["sd2"]
    ans = {
        "pns": {
            "meanRr": td["meanRr"],
            "rmssd": td["rmssd"],
            "sd1Pct": rounded(100 * sd1 / (sd1 + sd2), 1) if sd1 and sd2 else None,
        },
        "sns": {
            "meanHr": td["meanHr"],
            "stressIndex": td["stressIndex"],
            "sd2Pct": rounded(100 * sd2 / (sd1 + sd2), 1) if sd1 and sd2 else None,
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
    edges, counts = rr_histogram(det, TRIANGULAR_BIN_MS)
    series = {
        "tachogram": {
            "tS": np.round(t_all, 3).tolist(),
            "rrMs": np.round(rr_all, 1).tolist(),
            "rrCorrectedMs": np.round(rr_c, 1).tolist(),  # after artefact correction
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
