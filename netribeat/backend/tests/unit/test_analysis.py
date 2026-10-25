"""Every design-spec §6 formula against hand-computed or exactly known values, the
boundary rules, and golden checks on the supplied recordings."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from netribeat.analysis import beats, hrv
from netribeat.analysis.hr import hr_1hz, resolve_hr_max, zone_index, zone_metrics
from netribeat.analysis.pipeline import analyse
from netribeat.analysis.rpeaks import detect_r_peaks
from netribeat.parsers.base import EcgSegment, ParsedRecording, SignalKind
from netribeat.parsers.registry import parse_file

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "datasets"


def synthetic_ecg(
    peak_times_s: list[float], fs: float, duration_s: float, amp: float = 1.0
) -> np.ndarray:
    t = np.arange(int(duration_s * fs)) / fs
    x = np.zeros_like(t)
    for p in peak_times_s:
        x += amp * np.exp(-0.5 * ((t - p) / 0.008) ** 2)  # narrow QRS-like bump
    return x


# ------------------------------------------------------------- R-peaks


def test_r_peaks_found_at_true_positions() -> None:
    fs = 250.0
    truth = [0.5 + 0.8 * k for k in range(12)]
    peaks = detect_r_peaks(synthetic_ecg(truth, fs, 10.5), fs)
    assert np.allclose(peaks / fs, truth, atol=1 / fs)


def test_r_peaks_refractory_keeps_larger() -> None:
    fs = 250.0
    x = synthetic_ecg([1.0, 3.0], fs, 4.0) + synthetic_ecg([1.15], fs, 4.0, amp=0.95)
    peaks = detect_r_peaks(x, fs) / fs
    assert len(peaks) == 2 and peaks[0] == pytest.approx(1.0, abs=0.01)


def test_r_peaks_empty_and_flat_signals() -> None:
    assert detect_r_peaks(np.array([]), 250).size == 0
    assert detect_r_peaks(np.ones(1000), 250).size == 0


def test_rr_never_spans_a_gap() -> None:
    fs = 250.0
    a = EcgSegment(0.0, synthetic_ecg([0.5, 1.5, 2.5], fs, 3.0))
    b = EcgSegment(10.0, synthetic_ecg([0.5, 1.5], fs, 2.0))
    series, _ = beats.rr_from_ecg([a, b], fs)
    assert np.allclose(series.rr_ms, [1000, 1000, 1000], atol=4)
    assert np.allclose(series.t_s, [1.5, 2.5, 11.5], atol=0.005)
    assert series.peaks_detected == 5


# ------------------------------------------------------------- artefacts and quality


def test_artefact_above_20_percent_replaced_by_local_median() -> None:
    rr = np.full(21, 1000.0)
    rr[10] = 1300.0
    c = beats.correct_artefacts(rr)
    assert c.count == 1 and c.flags[10] and c.corrected[10] == 1000.0


def test_artefact_threshold_boundary() -> None:
    rr = np.full(21, 1000.0)
    rr[10] = 1200.0  # exactly 20 %: not "more than" 20 %
    assert beats.correct_artefacts(rr).count == 0
    rr[10] = 1200.5
    assert beats.correct_artefacts(rr).count == 1


def test_p4_out_of_range_flagged_even_when_local_median_agrees() -> None:
    rr = np.full(21, 2600.0)
    c = beats.correct_artefacts(rr)
    assert c.count == 21  # > 2500 ms everywhere (P4)


def test_window_truncated_at_edges() -> None:
    rr = np.array([1500.0, 1000, 1000, 1000, 1000, 1000, 1000])
    c = beats.correct_artefacts(rr)
    assert c.flags[0] and c.corrected[0] == 1000.0


@pytest.mark.parametrize(
    ("n", "pct", "expected"),
    [
        (29, 0.0, "no_ecg"),
        (30, 0.0, "good"),
        (30, 5.0, "good"),
        (30, 5.01, "poor"),
        (0, 0, "no_ecg"),
    ],
)
def test_quality_rules(n: int, pct: float, expected: str) -> None:
    assert beats.quality(n, pct) == expected


# ------------------------------------------------------------- HR, HRmax, zones, TRIMP


def test_hr_1hz_linear_interpolation() -> None:
    t = np.array([0.4, 1.4, 2.4, 3.4])
    rr = np.array([1000.0, 1000.0, 500.0, 500.0])  # 60, 60, 120, 120 bpm
    grid, bpm = hr_1hz(t, rr)
    assert grid.tolist() == [1.0, 2.0, 3.0]
    assert bpm == pytest.approx([60.0, 96.0, 120.0])


@pytest.mark.parametrize(
    ("kw", "value", "method"),
    [
        (
            {
                "user_method": "manual",
                "user_manual": 190,
                "session_override": 170,
                "age_at_recording": 30,
            },
            190,
            "manual",
        ),
        (
            {
                "user_method": "peak",
                "user_peak": 187.6,
                "session_override": 170,
                "age_at_recording": 30,
            },
            188,
            "peak",
        ),
        ({"user_method": "age", "session_override": 170, "age_at_recording": 30}, 180, "age"),
        ({"session_override": 170, "age_at_recording": 30}, 170, "manual"),
        ({"age_at_recording": 30}, 180, "age"),
    ],
)
def test_hr_max_precedence(kw: dict[str, object], value: int, method: str) -> None:
    base: dict[str, object] = {
        "user_method": None,
        "user_manual": None,
        "user_peak": None,
        "session_override": None,
        "age_at_recording": None,
    }
    hm = resolve_hr_max(**{**base, **kw})  # type: ignore[arg-type]
    assert hm is not None and (hm.value, hm.method) == (value, method)


def test_hr_max_unknown() -> None:
    assert (
        resolve_hr_max(
            user_method=None,
            user_manual=None,
            user_peak=None,
            session_override=None,
            age_at_recording=None,
        )
        is None
    )


def test_zone_boundaries() -> None:
    bpm = np.array([99.9, 100, 119.9, 120, 140, 160, 179.9, 180, 250])
    assert zone_index(bpm, 200).tolist() == [0, 1, 1, 2, 3, 4, 4, 5, 5]


def test_time_in_zone_and_edwards_trimp() -> None:
    hm = resolve_hr_max(
        user_method="manual",
        user_manual=200,
        user_peak=None,
        session_override=None,
        age_at_recording=None,
    )
    # 60 s in Z1 (110 bpm), 120 s in Z3 (150), 30 s below Z1 (90)
    bpm = np.array([110.0] * 60 + [150.0] * 120 + [90.0] * 30)
    z = zone_metrics(bpm, hm)
    assert z["timeInZonesS"] == {"belowZ1": 30, "z1": 60, "z2": 0, "z3": 120, "z4": 0, "z5": 0}
    assert z["trainingLoad"] == pytest.approx(1 * 1 + 2 * 3)  # Σ minutes × zone


def test_zone_metrics_without_hr_max() -> None:
    z = zone_metrics(np.array([100.0]), None)
    assert z["trainingLoad"] is None and "unknown" in z["zonesUnavailableReason"]


# ------------------------------------------------------------- HRV


def test_time_domain_hand_computed() -> None:
    rr = np.array([800.0, 810, 790, 850, 800])
    td = hrv.time_domain(rr)
    d = np.array([10.0, -20, 60, -50])
    assert td["rmssd"] == pytest.approx(np.sqrt(np.mean(d**2)))
    assert td["sdnn"] == pytest.approx(np.std(rr, ddof=1))
    assert td["pnni20"] == pytest.approx(50.0)  # |Δ| > 20: 60, 50 (20 is not > 20)
    assert td["pnni50"] == pytest.approx(25.0)  # only 60
    assert td["meanRr"] == pytest.approx(810.0)


def test_psd_total_power_equals_variance_and_finds_hf_peak() -> None:
    rng = np.random.default_rng(1)
    rr = 1000 + 40 * np.sin(2 * np.pi * 0.25 * np.arange(300)) + rng.normal(0, 2, 300)
    t = np.cumsum(rr) / 1000
    p = hrv.psd(t, rr)
    assert float(p.sum() * 0.002) == pytest.approx(float(np.var(rr, ddof=1)), rel=1e-9)
    fd = hrv.frequency_domain(t, rr)
    assert fd["bands"]["hf"]["peakHz"] == pytest.approx(0.25, abs=0.01)
    assert fd["bands"]["hf"]["powerPct"] > 90
    assert fd["bands"]["lf"]["powerNu"] + fd["bands"]["hf"]["powerNu"] == pytest.approx(100)
    assert hrv.respiratory_rate(fd["bands"]["hf"]["peakHz"])["value"] == pytest.approx(15, abs=0.6)


def test_psd_grid() -> None:
    assert hrv.FREQS[0] == pytest.approx(0.002) and hrv.FREQS[-1] == pytest.approx(0.5)
    assert hrv.FREQS.size == 250


def test_poincare_formulas() -> None:
    rr = np.array([800.0, 820, 790, 850, 805, 815, 780])
    pc = hrv.poincare(rr)
    sd1 = np.std(np.diff(rr), ddof=1) / np.sqrt(2)
    assert pc["sd1"] == pytest.approx(sd1)
    assert pc["sd2"] == pytest.approx(np.sqrt(2 * np.std(rr, ddof=1) ** 2 - sd1**2))


def test_constant_rr_gives_zero_variability_without_crashing() -> None:
    rr = np.full(60, 1000.0)
    assert hrv.time_domain(rr)["rmssd"] == 0.0
    fd = hrv.frequency_domain(np.cumsum(rr) / 1000, rr)
    assert fd["totalPower"] == 0.0 and fd["lfHf"] is None


def test_movement_load_formula() -> None:
    x = np.array([0.0, 3.0])
    y = np.array([0.0, 4.0])
    z = np.array([0.0, 0.0])
    assert hrv.movement_load(x, y, z) == pytest.approx(5 / 100)


# ------------------------------------------------------------- pipeline


def rr_recording(rr: np.ndarray) -> ParsedRecording:
    return ParsedRecording(
        format="t", kind=SignalKind.RR, duration_s=float(rr.sum() / 1000), unit="ms", rr_ms=rr
    )


def test_short_recording_reports_unavailable_reasons() -> None:
    r = analyse(rr_recording(np.full(20, 900.0)))
    m = r.metrics
    assert m["hr"] == {"min": None, "avg": None, "max": None}  # no numbers from 20 beats
    assert "at least 30 are needed" in m["unavailable"]["hr"]
    assert r.signals["hr"]["bpm"] == []
    assert m["quality"] == "no_ecg" and m["timeDomain"] is None
    assert "at least 30" in m["unavailable"]["timeDomain"]
    assert m["movementLoad"] is None and "accelerometer" in m["unavailable"]["movementLoad"]


def test_hrv_window_is_first_300_seconds() -> None:
    rr = np.concatenate([np.full(300, 1000.0), np.full(300, 500.0)])  # 300 s then faster
    m = analyse(rr_recording(rr)).metrics
    assert m["timeDomain"]["meanRr"] == pytest.approx(1000.0)
    assert m["timeDomain"]["beats"] == 300


def test_provisional_rules_and_version_are_reported() -> None:
    m = analyse(rr_recording(np.full(60, 900.0))).metrics
    assert set(m["provisionalRules"]) == {"P2", "P3", "P4", "P5"}
    assert m["analysisVersion"]


def golden(name: str) -> dict[str, object]:
    return analyse(parse_file(name, (FIX / name).read_bytes())).metrics


@pytest.mark.parametrize(
    ("ecg", "rr"), [("D1BLECG.json", "D1BLHR.json"), ("D2BLECG.json", "D2BLHRjson.json")]
)
def test_ecg_detection_agrees_with_sensor_rr(ecg: str, rr: str) -> None:
    """Independent check: R-peaks found in the ECG reproduce the sensor's own RR stream."""
    a, b = golden(ecg), golden(rr)
    assert a["hr"]["avg"] == pytest.approx(b["hr"]["avg"], abs=1.0)
    assert a["timeDomain"]["rmssd"] == pytest.approx(b["timeDomain"]["rmssd"], rel=0.05)
    assert a["reliability"]["reliable"] and b["reliability"]["reliable"]


def test_golden_d4_baseline() -> None:
    m = golden("D4BLHRV_BLHR.csv")
    assert m["quality"] == "good" and m["reliability"]["reliable"]
    assert m["beats"]["rrIntervals"] == 549 and m["beats"]["artefacts"] == 0
    assert m["hr"]["avg"] == pytest.approx(80.7, abs=0.1)
    assert m["timeDomain"]["rmssd"] == pytest.approx(24.1, abs=0.1)


def test_single_spike_recording_is_flagged_unreliable() -> None:
    m = golden("D3BLHRV_BLHR.csv")
    assert m["reliability"]["reliable"] is False
    assert m["warnings"][0].startswith("Beat detection is unreliable")
