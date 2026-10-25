from __future__ import annotations

import contextlib
import json
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from netribeat.parsers.base import ParserError, SignalKind, UnsupportedFormat
from netribeat.parsers.registry import parse_file

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "datasets"


def load(name: str) -> bytes:
    return (FIX / name).read_bytes()


def ecg_json(timestamps: list[int], per_packet: int = 16) -> bytes:
    data = [{"ecg": {"Timestamp": ts, "Samples": list(range(per_packet))}} for ts in timestamps]
    return json.dumps({"data": data}).encode()


# ------------------------------------------------------------- real files


def test_json_ecg_real_file() -> None:
    r = parse_file("D1BLECG.json", load("D1BLECG.json"))
    assert (r.format, r.kind, r.fs_hz, r.unit) == (
        "movesense_json_ecg",
        SignalKind.ECG,
        500.0,
        "raw",
    )
    assert r.sample_count == 152624 and len(r.segments) == 1
    assert r.duration_s == pytest.approx(305.25, abs=0.1)
    assert any("unit is not documented" in w for w in r.warnings)


def test_json_rr_real_file() -> None:
    r = parse_file("D1BLHR.json", load("D1BLHR.json"))
    assert (r.format, r.kind, r.unit) == ("movesense_json_rr", SignalKind.RR, "ms")
    assert r.rr_ms is not None and r.rr_ms.size == 376
    assert r.duration_s == pytest.approx(305.8, abs=0.1)
    assert r.metadata["sensor_average_hr_min"] == pytest.approx(65.4, abs=0.1)


def test_json_rr_keeps_out_of_range_values() -> None:
    r = parse_file("D1PMHR.json", load("D1PMHR.json"))
    assert r.rr_ms is not None and int((r.rr_ms > 2500).sum()) == 7  # kept for P4, not dropped


def test_csv_real_file_metadata_and_data_minimisation() -> None:
    r = parse_file("D4BLHRV_BLHR.csv", load("D4BLHRV_BLHR.csv"))
    assert (r.format, r.fs_hz, r.unit) == ("movesense_csv_ecg", 200.0, "mV")
    assert r.sample_count == 81808
    assert r.metadata["age"] == 18 and r.metadata["recorded_at"].startswith("2026-09-04T16:11:54")
    assert r.metadata["discarded_fields"] == ["gender", "serial"]
    assert "serial" not in r.metadata and "gender" not in r.metadata
    assert "213030001062" not in json.dumps(r.metadata)


def test_csv_single_spike_is_not_called_clipping() -> None:
    # D3 reaches ±4.11 mV in one sample only: a spike, not a clipped (flat-topped) signal.
    r = parse_file("D3BLHRV_BLHR.csv", load("D3BLHRV_BLHR.csv"))
    assert not any("clipping" in w for w in r.warnings)


def test_csv_flat_topped_signal_is_reported_as_clipping() -> None:
    values = np.clip(np.sin(np.arange(2000) / 10) * 2, -1, 1)
    body = "".join(f"{i * 0.005:.3f},{v:.4f}\n" for i, v in enumerate(values))
    r = parse_file("x.csv", (HEADER + body).encode())
    assert any("clipping" in w for w in r.warnings)


# ------------------------------------------------------------- JSON ECG timing


def test_rate_from_timestamps_not_packet_size() -> None:
    r = parse_file("x.json", ecg_json([i * 64 for i in range(200)]))  # 16 samples / 64 ms
    assert r.fs_hz == 250.0


def test_bunched_timestamps_are_not_gaps() -> None:
    ts = [i * 32 for i in range(300)]
    ts[100] = ts[99]  # two packets share a timestamp, then a doubled interval: no loss
    r = parse_file("x.json", ecg_json(ts))
    assert len(r.segments) == 1 and r.missing_fraction == 0.0


def test_lost_packets_split_segments() -> None:
    ts = [i * 32 for i in range(150)] + [150 * 32 + 96 + i * 32 for i in range(150)]
    r = parse_file("x.json", ecg_json(ts))
    assert len(r.segments) == 2
    assert r.metadata["gap_ms_total"] == pytest.approx(96, abs=1)
    assert r.segments[1].start_s == pytest.approx(150 * 16 / 500 + 0.096, abs=1e-6)
    assert any("gap" in w for w in r.warnings)


def test_more_than_ten_percent_missing_fails() -> None:
    ts = [i * 32 for i in range(100)] + [100 * 32 + 2000 + i * 32 for i in range(100)]
    with pytest.raises(ParserError, match="missing"):
        parse_file("x.json", ecg_json(ts))


@pytest.mark.parametrize(
    ("doc", "match"),
    [
        ({"data": []}, "empty"),
        ({"nope": 1}, "data"),
        ({"data": [{"ecg": {"Timestamp": 1}}]}, "Samples"),
        ({"data": [{"ecg": {"Timestamp": "x", "Samples": [1]}}]}, "number"),
        ({"data": [{"heartRate": {"rrData": [800, -5]}}]}, "positive"),
        ({"data": [{"heartRate": {"rrData": []}}]}, "No RR"),
        ({"data": [{"other": 1}]}, "not recognised"),
    ],
)
def test_invalid_json_documents(doc: object, match: str) -> None:
    with pytest.raises(ParserError, match=match):
        parse_file("x.json", json.dumps(doc).encode())


def test_backwards_timestamps_fail() -> None:
    ts = [i * 32 for i in range(50)]
    ts[30] = 5
    with pytest.raises(ParserError, match="backwards"):
        parse_file("x.json", ecg_json(ts))


# ------------------------------------------------------------- CSV edge cases

HEADER = '# created 2026-01-01T00:00:00Z\n# age 30\n#unit s mV\n"Elapsed time","ECG"\n'


def csv_bytes(times: list[float], header: str = HEADER) -> bytes:
    return (header + "".join(f"{t:.3f},{np.sin(t):.4f}\n" for t in times)).encode()


def test_csv_gap_creates_segments() -> None:
    times = [i * 0.005 for i in range(400)] + [2.1 + i * 0.005 for i in range(400)]
    r = parse_file("x.csv", csv_bytes(times))
    assert len(r.segments) == 2 and r.fs_hz == 200.0


def test_csv_errors_report_line_numbers() -> None:
    bad = (HEADER + "".join(f"{i * 0.005:.3f},0.1\n" for i in range(150)) + "0.8,abc\n").encode()
    with pytest.raises(ParserError, match=r"Line 155: not a number"):
        parse_file("x.csv", bad)
    rev = csv_bytes([i * 0.005 for i in range(150)] + [0.1])
    with pytest.raises(ParserError, match="does not increase"):
        parse_file("x.csv", rev)


def test_csv_other_unit_is_kept_and_warned() -> None:
    r = parse_file("x.csv", csv_bytes([i * 0.005 for i in range(200)], HEADER.replace("mV", "uV")))
    assert r.unit == "uV" and any("not mV" in w for w in r.warnings)


# ------------------------------------------------------------- unsupported input


def test_hex_is_explicitly_unsupported() -> None:
    with pytest.raises(UnsupportedFormat, match="sensor-formats.md"):
        parse_file("rec.hex", b"0A1B2C3D\n4E5F6071\n")


@pytest.mark.parametrize("raw", [b"", b"   ", b"hello world", b"a,b\n1,2\n", b"\xff\xfe\x00\x01"])
def test_unrecognised_or_empty(raw: bytes) -> None:
    with pytest.raises(ParserError):
        parse_file("x", raw)


@settings(max_examples=200, deadline=None)
@given(st.binary(max_size=2000))
def test_arbitrary_bytes_never_crash(raw: bytes) -> None:
    with contextlib.suppress(ParserError):  # any other exception fails the test
        parse_file("fuzz", raw)


@settings(max_examples=100, deadline=None)
@given(
    st.recursive(
        st.none() | st.booleans() | st.integers() | st.text(max_size=5),
        lambda c: st.lists(c, max_size=4) | st.dictionaries(st.text(max_size=8), c, max_size=4),
        max_leaves=20,
    )
)
def test_arbitrary_json_never_crashes(doc: object) -> None:
    with contextlib.suppress(ParserError):
        parse_file("fuzz.json", json.dumps({"data": [doc]}).encode())


@pytest.mark.parametrize(
    ("label", "encode"),
    [
        ("utf-8 bom", lambda t: b"\xef\xbb\xbf" + t.encode()),
        ("utf-16 le bom", lambda t: t.encode("utf-16")),  # PowerShell 5 '>' / Out-File
        ("utf-16 be bom", lambda t: b"\xfe\xff" + t.encode("utf-16-be")),
    ],
)
@pytest.mark.parametrize(
    ("name", "fmt"),
    [("D1BLHR.json", "movesense_json_rr"), ("D4BLHRV_BLHR.csv", "movesense_csv_ecg")],
)
def test_windows_encodings_are_accepted(label: str, encode: object, name: str, fmt: str) -> None:
    from netribeat.parsers.registry import sniff

    raw = encode((FIX / name).read_text(encoding="utf-8"))  # type: ignore[operator]
    assert sniff(raw) in {"json", "csv"}
    assert parse_file(name, raw).format == fmt


def test_broken_utf16_is_reported() -> None:
    with pytest.raises(ParserError, match="UTF-16"):
        parse_file("x.json", b"\xff\xfe\x00\xd8")
