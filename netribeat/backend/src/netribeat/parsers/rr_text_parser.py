"""RR-interval text files (Kubios-compatible) and their JSON equivalent.

Text / CSV (.csv, .txt): one RR interval per line, e.g. the supplied
``D1BLHR_RR.csv`` (integers in ms, CRLF, no header). Also accepted: an optional header
line, several columns with a header that names the RR column (``rr``, ``rri``, ``ibi``,
``nn``, ``interval``), and comma / semicolon / tab / space delimiters.

JSON: ``[812, 790, …]`` or ``{"rr": [...]}`` (also ``rrIntervals``, ``rr_ms``, ``ibi``).
The Movesense ``data[].heartRate.rrData`` format is handled by json_parser.

Units: values whose median lies in 250–2500 are milliseconds; in 0.25–2.5 they are
seconds and are converted to ms (×1000) with a warning. Anything else is rejected rather
than guessed.
"""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

from netribeat.parsers.base import ParsedRecording, ParserError, SignalKind

RR_HEADER = re.compile(r"\b(rr|rri|ibi|nn|interval|rr[_ ]?ms|rr[_ ]?interval)\b", re.I)
JSON_KEYS = ("rr", "RR", "rrIntervals", "rr_intervals", "rr_ms", "rrMs", "ibi", "IBI")
_SPLIT = re.compile(r"[,;\t ]+")


def _is_number(token: str) -> bool:
    try:
        return math.isfinite(float(token))
    except ValueError:
        return False


def _to_ms(values: np.ndarray, warnings: list[str]) -> np.ndarray:
    if values.size < 2:
        raise ParserError("At least 2 RR intervals are needed")
    if np.any(values <= 0):
        raise ParserError("RR intervals must be positive")
    med = float(np.median(values))
    if 250 <= med <= 2500:
        return values.astype(np.float64)
    if 0.25 <= med <= 2.5:
        warnings.append("RR values were in seconds and have been converted to milliseconds")
        return values.astype(np.float64) * 1000.0
    raise ParserError(
        f"RR values don't look like milliseconds or seconds (median {med:g}); "
        "expected about 250–2500 ms"
    )


def _recording(
    rr: np.ndarray, fmt: str, warnings: list[str], meta: dict[str, Any]
) -> ParsedRecording:
    if np.all(rr % 2 == 0):
        warnings.append("RR values are multiples of 2 ms (resolution ≤ 2 ms)")
    meta["rr_count"] = int(rr.size)
    return ParsedRecording(
        format=fmt,
        kind=SignalKind.RR,
        duration_s=float(rr.sum() / 1000.0),
        unit="ms",
        rr_ms=rr,
        metadata=meta,
        warnings=warnings,
    )


def looks_like_text(text: str) -> bool:
    """True when the first data lines are numbers (optionally after one header line)."""
    lines = [
        ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    ]
    if len(lines) < 2:
        return False
    body = lines[1:6] if not _is_number(_SPLIT.split(lines[0])[0]) else lines[:5]
    return bool(body) and all(_is_number(_SPLIT.split(b)[0]) for b in body)


def parse_text(raw: bytes) -> ParsedRecording:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ParserError("RR file is not UTF-8 text") from None
    rows = [
        (n, ln.strip())
        for n, ln in enumerate(text.splitlines(), start=1)
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    if not rows:
        raise ParserError("The file is empty")
    col = 0
    header: list[str] | None = None
    first = _SPLIT.split(rows[0][1])
    if not all(_is_number(t) for t in first):
        header = [h.strip().strip('"') for h in first]
        rows = rows[1:]
        named = [i for i, h in enumerate(header) if RR_HEADER.search(h)]
        if len(header) > 1 and not named:
            raise ParserError(
                "Several columns but none is named RR (expected a header such as 'RR (ms)')"
            )
        col = named[0] if named else 0
    values: list[float] = []
    for n, line in rows:
        tokens = _SPLIT.split(line)
        if header is None and len(tokens) > 1:
            raise ParserError(f"Line {n}: several values but no header naming the RR column")
        if col >= len(tokens) or not _is_number(tokens[col]):
            raise ParserError(f"Line {n}: not a number")
        values.append(float(tokens[col]))
    warnings: list[str] = []
    rr = _to_ms(np.asarray(values), warnings)
    meta: dict[str, Any] = {}
    if header:
        meta["rr_column"] = header[col][:40]
    return _recording(rr, "rr_text", warnings, meta)


def json_rr_values(doc: Any) -> list[Any] | None:
    if (
        isinstance(doc, list)
        and doc
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in doc)
    ):
        return doc
    if isinstance(doc, dict):
        for k in JSON_KEYS:
            v = doc.get(k)
            if isinstance(v, list):
                return v
    return None


def parse_json_rr(values: list[Any]) -> ParsedRecording:
    nums: list[float] = []
    for i, v in enumerate(values):
        if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
            raise ParserError(f"RR value {i}: expected a number")
        nums.append(float(v))
    warnings: list[str] = []
    return _recording(_to_ms(np.asarray(nums), warnings), "rr_json", warnings, {})
