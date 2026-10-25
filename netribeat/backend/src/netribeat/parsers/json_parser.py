"""Movesense-style JSON exports (the supplied D1/D2 files).

ECG: ``{"data": [{"ecg": {"Timestamp": <ms>, "Samples": [int, …]}}, …]}``
RR:  ``{"data": [{"heartRate": {"rrData": [ms, …], "average": bpm}}, …]}``

Evidence (docs/dataset-analysis.md): Timestamp is in ms; a linear fit gives exactly
32.000 ms per 16-sample packet, i.e. 500 Hz. The rate is derived from the timestamps of
each file (never from the packet size) and must be consistent. Sample units are
undocumented, so they stay "raw".
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from netribeat.parsers.base import EcgSegment, ParsedRecording, ParserError, SignalKind

MAX_MISSING_FRACTION = 0.10  # P2 (provisional): >10 % missing samples fails the recording
RATE_ROUNDING_TOLERANCE = 0.01  # a derived rate within 1 % of an integer is that integer


def _records(doc: Any) -> list[Any]:
    if not isinstance(doc, dict) or not isinstance(doc.get("data"), list):
        raise ParserError('Expected a JSON object with a "data" list')
    if not doc["data"]:
        raise ParserError('The "data" list is empty')
    return list(doc["data"])


def looks_like(doc: Any) -> str | None:
    """Return "ecg" / "rr" when the document has the expected structure."""
    try:
        records = _records(doc)
    except ParserError:
        return None
    first = records[0] if isinstance(records[0], dict) else {}
    if isinstance(first.get("ecg"), dict):
        return "ecg"
    if isinstance(first.get("heartRate"), dict):
        return "rr"
    return None


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ParserError(f"{where}: expected a number")
    return float(value)


def parse_rr(doc: Any) -> ParsedRecording:
    records = _records(doc)
    rr: list[float] = []
    averages: list[float] = []
    for i, rec in enumerate(records):
        hr = rec.get("heartRate") if isinstance(rec, dict) else None
        if not isinstance(hr, dict):
            raise ParserError(f"Record {i}: missing heartRate object")
        values = hr.get("rrData", [])
        if not isinstance(values, list):
            raise ParserError(f"Record {i}: rrData must be a list")
        for v in values:
            ms = _number(v, f"Record {i} rrData")
            if ms <= 0:
                raise ParserError(f"Record {i}: RR must be positive")
            rr.append(ms)
        if "average" in hr:
            averages.append(_number(hr["average"], f"Record {i} average"))
    if not rr:
        raise ParserError("No RR intervals found (rrData is empty in every record)")
    arr = np.asarray(rr, dtype=np.float64)
    meta: dict[str, Any] = {"records": len(records), "rr_count": int(arr.size)}
    if averages:
        # The sensor's own running average: kept for reference only; it has no timestamps,
        # so it cannot form a 1 Hz series.
        meta["sensor_average_hr_min"] = round(min(averages), 1)
        meta["sensor_average_hr_max"] = round(max(averages), 1)
    warnings = []
    if np.all(arr % 8 == 0):
        warnings.append("RR values are multiples of 8 ms (sensor resolution ≤ 8 ms)")
    return ParsedRecording(
        format="movesense_json_rr",
        kind=SignalKind.RR,
        duration_s=float(arr.sum() / 1000.0),
        unit="ms",
        rr_ms=arr,
        metadata=meta,
        warnings=warnings,
    )


def derive_rate(ts_ms: np.ndarray, counts: np.ndarray) -> float:
    """Sampling rate from timestamps: median per-sample interval over packets with a
    positive interval (bunched packets with dt = 0 are excluded), rounded to an integer
    when within 1 %."""
    dt = np.diff(ts_ms)
    per_sample = dt[dt > 0] / counts[:-1][dt > 0]
    if per_sample.size < 10:
        raise ParserError("Too few ECG packets with increasing timestamps to derive the rate")
    fs = 1000.0 / float(np.median(per_sample))
    nearest = round(fs)
    if nearest > 0 and abs(fs - nearest) / nearest <= RATE_ROUNDING_TOLERANCE:
        fs = float(nearest)
    return fs


def split_gaps(
    ts_ms: np.ndarray, counts: np.ndarray, fs: float
) -> tuple[list[tuple[int, int]], list[float]]:
    """Find recording gaps from packet timestamps.

    residual_i = ts_i − ts_0 − (samples before packet i) / fs. Bunched timestamps dip
    below the running maximum and come back (no data lost); lost packets push the
    residual permanently above it. A gap starts at packet i when residual_i exceeds the
    previous running maximum by more than half a packet. Returns packet index ranges
    [start, end) and the gap durations in ms.
    """
    before = np.concatenate([[0], np.cumsum(counts)[:-1]])
    residual = ts_ms - ts_ms[0] - before * 1000.0 / fs
    half_packet = float(np.median(counts)) * 1000.0 / fs / 2.0
    ranges: list[tuple[int, int]] = []
    gaps: list[float] = []
    start = 0
    running_max = residual[0]
    for i in range(1, len(residual)):
        jump = residual[i] - running_max
        if jump > half_packet:
            ranges.append((start, i))
            gaps.append(float(jump))
            start = i
        running_max = max(running_max, residual[i])
    ranges.append((start, len(residual)))
    return ranges, gaps


def parse_ecg(doc: Any) -> ParsedRecording:
    records = _records(doc)
    ts: list[float] = []
    packets: list[list[float]] = []
    for i, rec in enumerate(records):
        ecg = rec.get("ecg") if isinstance(rec, dict) else None
        if not isinstance(ecg, dict):
            raise ParserError(f"Record {i}: missing ecg object")
        samples = ecg.get("Samples")
        if not isinstance(samples, list) or not samples:
            raise ParserError(f"Record {i}: Samples must be a non-empty list")
        ts.append(_number(ecg.get("Timestamp"), f"Record {i} Timestamp"))
        packets.append([_number(v, f"Record {i} Samples") for v in samples])
    ts_ms = np.asarray(ts, dtype=np.float64)
    if np.any(np.diff(ts_ms) < 0):
        raise ParserError("ECG timestamps go backwards; the file may be corrupted")
    counts = np.asarray([len(p) for p in packets], dtype=np.float64)
    fs = derive_rate(ts_ms, counts)
    ranges, gaps = split_gaps(ts_ms, counts, fs)

    segments: list[EcgSegment] = []
    elapsed_s = 0.0
    for k, (a, b) in enumerate(ranges):
        if k > 0:
            elapsed_s += gaps[k - 1] / 1000.0
        samples = np.asarray([v for p in packets[a:b] for v in p], dtype=np.float64)
        segments.append(EcgSegment(start_s=elapsed_s, samples=samples))
        elapsed_s += samples.size / fs
    total_samples = float(counts.sum())
    missing_s = sum(gaps) / 1000.0
    duration_s = total_samples / fs + missing_s
    missing_fraction = missing_s / duration_s if duration_s > 0 else 0.0
    if missing_fraction > MAX_MISSING_FRACTION:
        raise ParserError(
            f"{missing_fraction * 100:.1f} % of the recording is missing (limit 10 %)"
        )
    warnings = []
    if gaps:
        warnings.append(
            f"{len(gaps)} recording gap(s) totalling {sum(gaps):.0f} ms; "
            "RR intervals are not computed across gaps"
        )
    warnings.append("ECG sample unit is not documented for this format; values are raw units")
    bunched = int(np.sum(np.diff(ts_ms) == 0))
    return ParsedRecording(
        format="movesense_json_ecg",
        kind=SignalKind.ECG,
        duration_s=duration_s,
        unit="raw",
        fs_hz=fs,
        segments=segments,
        missing_fraction=missing_fraction,
        metadata={
            "packets": len(records),
            "samples": int(total_samples),
            "gaps": len(gaps),
            "gap_ms_total": round(sum(gaps), 1),
            "bunched_timestamps": bunched,
        },
        warnings=warnings,
    )


def parse(raw: bytes) -> ParsedRecording:
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParserError(f"Not valid JSON ({exc.__class__.__name__})") from None
    from netribeat.parsers.rr_text_parser import json_rr_values, parse_json_rr

    simple = json_rr_values(doc)
    if simple is not None:  # [812, 790, …] or {"rr": [...]}: same content as an RR CSV
        return parse_json_rr(simple)
    _records(doc)  # specific message for a missing or empty "data" list
    kind = looks_like(doc)
    if kind == "ecg":
        return parse_ecg(doc)
    if kind == "rr":
        return parse_rr(doc)
    raise ParserError("JSON structure not recognised (expected data[].ecg or data[].heartRate)")
