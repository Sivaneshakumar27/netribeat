"""Advanced HRV (Kubios-compatible definitions): known-answer and reference tests."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from netribeat.analysis import advanced as adv
from netribeat.parsers.registry import parse_file

RR = Path(__file__).resolve().parents[1] / "fixtures" / "rr"


def sampen_reference(x: list[float], m: int, r: float) -> float:
    """Brute-force SampEn (Richman & Moorman): N − m templates for both lengths."""
    n = len(x)

    def matches(mm: int) -> int:
        count = 0
        for i in range(n - m):
            for j in range(i + 1, n - m):
                if all(abs(x[i + k] - x[j + k]) <= r for k in range(mm)):
                    count += 1
        return count

    return -math.log(matches(m + 1) / matches(m))


def apen_reference(x: list[float], m: int, r: float) -> float:
    n = len(x)

    def phi(mm: int) -> float:
        total = 0.0
        for i in range(n - mm + 1):
            c = sum(
                all(abs(x[i + k] - x[j + k]) <= r for k in range(mm)) for j in range(n - mm + 1)
            )
            total += math.log(c / (n - mm + 1))
        return total / (n - mm + 1)

    return phi(m) - phi(m + 1)


def test_sampen_and_apen_match_reference() -> None:
    rng = np.random.default_rng(3)
    x = (800 + rng.normal(0, 40, 120)).tolist()
    r = 0.2 * float(np.std(x, ddof=1))
    assert adv.sampen(np.asarray(x), 2, r) == pytest.approx(sampen_reference(x, 2, r), rel=1e-12)
    assert adv.apen(np.asarray(x), 2, r) == pytest.approx(apen_reference(x, 2, r), rel=1e-12)


def test_entropy_lower_for_regular_signal() -> None:
    rng = np.random.default_rng(1)
    regular = 800 + 50 * np.sin(np.arange(300) * 2 * np.pi / 10)
    noisy = 800 + rng.normal(0, 50, 300)
    r = lambda v: 0.2 * float(np.std(v, ddof=1))  # noqa: E731
    assert adv.apen(regular, 2, r(regular)) < adv.apen(noisy, 2, r(noisy))


def test_dfa_white_noise_and_brownian() -> None:
    rng = np.random.default_rng(7)
    white = rng.normal(0, 1, 4000)
    a_white, _ = adv.dfa(white, (16, 64))
    a_brown, _ = adv.dfa(np.cumsum(white), (16, 64))
    assert a_white == pytest.approx(0.5, abs=0.1)
    assert a_brown == pytest.approx(1.5, abs=0.12)


def test_smoothness_priors_removes_linear_trend_and_keeps_fast_oscillation() -> None:
    n = 400
    lin = np.linspace(700, 900, n)
    assert np.allclose(
        adv.smoothness_priors(lin, 500), lin, atol=1e-6
    )  # linear = in the null space
    fast = 30 * np.sin(np.arange(n) * 2 * np.pi / 4)
    trend = adv.smoothness_priors(lin + fast, 500)
    assert np.allclose(trend, lin, atol=1.0)


def test_threshold_correction_levels() -> None:
    rng = np.random.default_rng(0)
    rr = 1000 + rng.normal(0, 20, 200)
    rr[100] = 1600  # +600 ms spike
    t = np.cumsum(rr) / 1000
    fixed, flags = adv.threshold_correction(t, rr, "medium")  # 250 ms at 60 bpm
    assert flags[100] and flags.sum() == 1
    assert fixed[100] == pytest.approx(1000, abs=60)
    _, none_flags = adv.threshold_correction(t, rr, "very_low")  # 450 ms threshold
    assert none_flags[100] and none_flags.sum() == 1
    _, strict = adv.threshold_correction(t, rr, "very_strong")  # 50 ms: also flags noise
    assert strict.sum() > 1


def test_stress_index_hand_computed() -> None:
    rr = np.array([775.0] * 50 + [825.0] * 30 + [875.0] * 20)  # 50 ms bins
    si, parts = adv.stress_index(rr)
    mode = 0.775  # centre of the 750–800 ms bin
    amo = 50.0
    mxdmn = 0.100
    assert parts["amoPct"] == pytest.approx(amo)
    assert parts["modeS"] == pytest.approx(mode)
    assert si == pytest.approx(math.sqrt(amo / (2 * mode * mxdmn)))


def test_triangular_index_and_tinn_on_triangle() -> None:
    # A symmetric triangular histogram spanning 1000 ms ± 125 ms in 7.8125 ms steps
    vals = []
    for k in range(-16, 17):
        vals += [1000 + k * adv.TRIANGULAR_BIN_MS] * (17 - abs(k))
    rr = np.asarray(vals)
    _, counts = adv._histogram(rr, adv.TRIANGULAR_BIN_MS)
    assert rr.size / counts.max() == pytest.approx(rr.size / 17)
    assert adv.tinn(rr) == pytest.approx(34 * adv.TRIANGULAR_BIN_MS, abs=2 * adv.TRIANGULAR_BIN_MS)


def test_time_domain_definitions() -> None:
    rr = np.array([800.0, 860, 790, 800, 900, 850, 800])
    td = adv.time_domain(rr, rr, adv.AdvancedOptions())
    d = np.diff(rr)  # 60, -70, 10, 100, -50, -50
    assert td["nn50"] == 3  # |Δ| > 50: 60, 70, 100 (50 is not > 50)
    assert td["pnn50"] == pytest.approx(round(100 * 3 / 6, 2))  # denominator n − 1
    assert td["rmssd"] == pytest.approx(round(float(np.sqrt(np.mean(d * d))), 2))
    hr5 = np.convolve(60000 / rr, np.ones(5) / 5, mode="valid")
    assert td["maxHr"] == pytest.approx(round(float(hr5.max()), 1))
    assert td["minHr"] == pytest.approx(round(float(hr5.min()), 1))


def test_spectra_find_the_modulation_and_ar_preserves_variance() -> None:
    n = 500
    rr = 900 + 40 * np.sin(2 * np.pi * 0.25 * np.cumsum(np.full(n, 0.9)))  # 0.25 Hz, HF
    t = np.cumsum(rr) / 1000
    opts = adv.AdvancedOptions()
    fd, series = adv.frequency_domain(t, rr, opts)
    for method in ("fft", "ar", "lomb"):
        assert fd[method]["bands"]["hf"]["peakHz"] == pytest.approx(0.25, abs=0.01), method
    b = fd["fft"]["bands"]
    assert b["lf"]["powerNu"] + b["hf"]["powerNu"] == pytest.approx(100, abs=0.01)
    assert b["hf"]["logPower"] == pytest.approx(math.log(b["hf"]["power"]), abs=1e-3)  # natural log
    _, x = adv.resample(t, rr, 4.0)
    f, p = adv.ar_psd(x, opts, adv.AR_INTEGRATION_POINTS_PER_HZ)
    assert float(np.trapezoid(p, f)) == pytest.approx(float(np.var(x - x.mean())), rel=0.01)
    # Band powers use the fine grid, so even a near-line spectrum isn't inflated:
    ar_total = fd["ar"]["totalPower"]
    assert ar_total == pytest.approx(float(np.var(x - x.mean())), rel=0.05)


def test_recurrence_measures_in_range() -> None:
    rr = 900 + 40 * np.sin(np.arange(300) * 2 * np.pi / 8)
    rq = adv.recurrence(rr, 10, float(np.std(rr, ddof=1)))
    assert 0 < rq["rec"] <= 100 and rq["det"] > 90 and rq["lmax"] >= 2


def test_sample_selection_and_options() -> None:
    rr = parse_file("x.csv", (RR / "D1PMHR_RR_trimmed.csv").read_bytes()).rr_ms
    t = np.cumsum(rr) / 1000
    res = adv.analyse_advanced(t, rr, adv.AdvancedOptions(sample_start_s=600, sample_length_s=120))
    s = res.metrics["sample"]
    assert s["startS"] == 600 and s["lengthS"] == pytest.approx(120, abs=1)
    assert all(600 < v <= 721 for v in res.series["sample"]["tS"])
    assert any("2 minutes" in w for w in res.metrics["warnings"]) is False
    with pytest.raises(ValueError, match="correction"):
        adv.AdvancedOptions(correction="magic").validated()
    with pytest.raises(ValueError, match="≥ 30 s"):
        adv.AdvancedOptions(sample_length_s=10).validated()


def test_whole_long_recording_skips_quadratic_measures_with_reason() -> None:
    rr = np.full(4500, 800.0) + np.random.default_rng(0).normal(0, 20, 4500)
    res = adv.analyse_advanced(np.cumsum(rr) / 1000, rr, adv.AdvancedOptions(sample_length_s=None))
    assert res.metrics["nonlinear"]["apen"] is None
    assert "4000 beats" in res.metrics["unavailable"]["apen"]
    assert res.metrics["nonlinear"]["dfaAlpha1"] is not None


def test_too_few_beats_is_unavailable() -> None:
    rr = np.full(20, 800.0)
    res = adv.analyse_advanced(np.cumsum(rr) / 1000, rr, adv.AdvancedOptions())
    assert "at least 30" in res.metrics["unavailable"]["all"].lower()


def test_ecg_derived_and_sensor_rr_agree() -> None:
    """Two independent RR sources for the same D1 baseline recording."""
    out = []
    for name in ("D1BLHR_RR.csv", "D1BLECG_RR_fromECG.csv"):
        rr = parse_file(name, (RR / name).read_bytes()).rr_ms
        out.append(adv.analyse_advanced(np.cumsum(rr) / 1000, rr, adv.AdvancedOptions()).metrics)
    a, b = out
    assert a["timeDomain"]["rmssd"] == pytest.approx(b["timeDomain"]["rmssd"], rel=0.03)
    assert a["timeDomain"]["sdnn"] == pytest.approx(b["timeDomain"]["sdnn"], rel=0.03)
    assert a["nonlinear"]["dfaAlpha1"] == pytest.approx(b["nonlinear"]["dfaAlpha1"], abs=0.05)


def test_default_low_correction_leaves_clean_baseline_untouched() -> None:
    rr = parse_file("x", (RR / "D1BLHR_RR.csv").read_bytes()).rr_ms
    res = adv.analyse_advanced(np.cumsum(rr) / 1000, rr, adv.AdvancedOptions())
    assert res.metrics["sample"]["beatsCorrected"] == 0
