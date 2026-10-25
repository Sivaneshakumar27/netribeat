"""Movesense CSV ECG exports (the supplied D3/D4/D6 files).

    # created 2026-09-05T02:35:06.290106Z
    # device Movesense
    # serial …           (discarded: not needed — CLAUDE.md data minimisation)
    # bandwidth 10 - 33 Hz
    # gender …           (discarded)
    # age 18
    #name elapsed_time ECG_mv
    #datatype decimal decimal
    #unit s mV
    "Elapsed time","ECG"
    0,0.0123

Evidence: elapsed time in seconds, rounded to 1 ms; a linear fit gives exactly 200 Hz.
"""

from __future__ import annotations

import contextlib
import itertools
import math
from datetime import datetime
from typing import Any

import numpy as np

from netribeat.parsers.base import EcgSegment, ParsedRecording, ParserError, SignalKind

DISCARDED_FIELDS = {"serial", "gender"}
RATE_ROUNDING_TOLERANCE = 0.005


def looks_like(text: str) -> bool:
    for line in text.splitlines()[:40]:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        low = s.lower().replace('"', "")
        return "elapsed time" in low and "ecg" in low
    return False


def _meta(lines: list[str]) -> tuple[dict[str, Any], list[str], str]:
    meta: dict[str, Any] = {}
    discarded: list[str] = []
    unit = "unknown"
    for line in lines:
        body = line.lstrip("#").strip()
        if not body:
            continue
        key, _, value = body.partition(" ")
        key, value = key.lower(), value.strip()
        if key in DISCARDED_FIELDS:
            discarded.append(key)
        elif key == "created":
            try:
                meta["recorded_at"] = datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).isoformat()
            except ValueError:
                meta["recorded_at_raw"] = value[:64]
        elif key == "age":
            with contextlib.suppress(ValueError):
                meta["age"] = int(value)
        elif key in {"device", "bandwidth"}:
            meta[key] = value[:100]
        elif key == "unit":
            parts = value.split()
            if len(parts) >= 2:
                unit = parts[1]
    if discarded:
        meta["discarded_fields"] = sorted(discarded)
    return meta, discarded, unit


def parse(raw: bytes) -> ParsedRecording:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ParserError("CSV is not UTF-8 text") from None
    lines = text.splitlines()
    comments, header_idx = [], None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#"):
            comments.append(s)
            continue
        if s:
            header_idx = i
            break
    if header_idx is None or not looks_like(text):
        raise ParserError('CSV header not recognised (expected "Elapsed time","ECG")')
    meta, _, unit = _meta(comments)

    t_list: list[float] = []
    v_list: list[float] = []
    for n, line in enumerate(lines[header_idx + 1 :], start=header_idx + 2):
        s = line.strip()
        if not s:
            continue
        parts = s.split(",")
        if len(parts) < 2:
            raise ParserError(f"Line {n}: expected two comma-separated values")
        try:
            t_val, v_val = float(parts[0]), float(parts[1])
        except ValueError:
            raise ParserError(f"Line {n}: not a number") from None
        if not (math.isfinite(t_val) and math.isfinite(v_val)):
            raise ParserError(f"Line {n}: not a finite number")
        t_list.append(t_val)
        v_list.append(v_val)
    if len(t_list) < 100:
        raise ParserError("Too few ECG samples (need at least 100)")
    t = np.asarray(t_list)
    v = np.asarray(v_list)
    dt = np.diff(t)
    if np.any(dt <= 0):
        bad_line = int(np.argmax(dt <= 0)) + header_idx + 3
        raise ParserError(f"Line {bad_line}: elapsed time does not increase")

    fs = 1.0 / float(np.median(dt))
    # Timestamps are rounded to 1 ms, so the median step can be off; refine by a linear fit
    # over sample index when the series has no gaps.
    gap_idx = np.where(dt > 1.5 / fs)[0]
    if gap_idx.size == 0:
        slope = float(np.polyfit(np.arange(t.size), t, 1)[0])
        fs = 1.0 / slope
    nearest = round(fs)
    if nearest > 0 and abs(fs - nearest) / nearest <= RATE_ROUNDING_TOLERANCE:
        fs = float(nearest)

    bounds = [0, *(gap_idx + 1).tolist(), t.size]
    segments = [
        EcgSegment(start_s=float(t[a] - t[0]), samples=v[a:b].astype(np.float64))
        for a, b in itertools.pairwise(bounds)
        if b > a
    ]
    duration_s = float(t[-1] - t[0]) + 1.0 / fs
    covered = sum(s.samples.size for s in segments) / fs
    missing_fraction = max(0.0, 1.0 - covered / duration_s)
    if missing_fraction > 0.10:
        raise ParserError(
            f"{missing_fraction * 100:.1f} % of the recording is missing (limit 10 %)"
        )
    warnings = []
    if gap_idx.size:
        warnings.append(
            f"{gap_idx.size} gap(s) in elapsed time; RR intervals are not computed across gaps"
        )
    if unit.lower() != "mv":
        warnings.append(f"Declared ECG unit is {unit!r}, not mV")
    peak = float(np.max(np.abs(v)))
    if peak > 0 and np.mean(np.isclose(np.abs(v), peak)) > 0.0005:
        warnings.append(f"Signal reaches ±{peak:g} {unit} repeatedly — possible clipping")
    meta["samples"] = int(t.size)
    return ParsedRecording(
        format="movesense_csv_ecg",
        kind=SignalKind.ECG,
        duration_s=duration_s,
        unit="mV" if unit.lower() == "mv" else unit,
        fs_hz=fs,
        segments=segments,
        missing_fraction=missing_fraction,
        metadata=meta,
        warnings=warnings,
    )
