"""Format detection by content (not file name). Adding a format = one new entry here."""

from __future__ import annotations

import json
import re

from netribeat.parsers import csv_parser, json_parser, rr_text_parser
from netribeat.parsers.base import ParsedRecording, ParserError, UnsupportedFormat

SUPPORTED_DESCRIPTION = (
    "Movesense JSON (ECG or RR), Movesense CSV ECG, and RR-interval lists (.csv/.txt one value "
    'per line, or JSON [..] / {"rr": [..]})'
)
_HEX = re.compile(rb"^[\s0-9A-Fa-f]+$")
_HEX_LETTER = re.compile(rb"[A-Fa-f]")


def _looks_hex(raw: bytes) -> bool:
    """Hex digits only AND at least one letter A–F (a list of decimal numbers is not HEX)."""
    sample = raw[:4096]
    return bool(_HEX.match(sample)) and bool(_HEX_LETTER.search(sample))


def normalise_encoding(raw: bytes) -> bytes:
    """Return UTF-8 bytes without a byte-order mark. Windows tools often save text as
    UTF-8 with a BOM (Notepad, Excel "CSV UTF-8") or as UTF-16 (Windows PowerShell 5
    `>`/Out-File, Excel "Unicode Text"); all of these are accepted."""
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16").encode("utf-8")
        except UnicodeDecodeError:
            raise ParserError("The file looks like UTF-16 text but can't be decoded") from None
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:]
    return raw


def parse_file(filename: str, raw: bytes) -> ParsedRecording:
    raw = normalise_encoding(raw)
    if not raw.strip():
        raise ParserError("The file is empty")
    head = raw.lstrip()[:1]
    if head in (b"{", b"["):
        return json_parser.parse(raw)
    sample = raw[:4096]
    try:
        text = sample.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = ""
    if text and csv_parser.looks_like(text):
        return csv_parser.parse(raw)
    if text and rr_text_parser.looks_like_text(text):
        return rr_text_parser.parse_text(raw)
    if _looks_hex(raw):
        raise UnsupportedFormat(
            "Sensor HEX files are not supported yet: their format specification "
            "(docs/sensor-formats.md) has not been provided"
        )
    raise UnsupportedFormat(f"File format not recognised. Supported: {SUPPORTED_DESCRIPTION}")


def sniff(raw: bytes) -> str:
    """Cheap format check at upload time (the full parse runs in the background job).
    Returns "json" or "csv"; raises UnsupportedFormat / ParserError otherwise."""
    raw = normalise_encoding(raw[:262144])
    if not raw.strip():
        raise ParserError("The file is empty")
    head = raw.lstrip()[:1]
    window = raw[:65536]
    if head in (b"{", b"["):
        if b'"ecg"' in window or b'"heartRate"' in window:
            return "json"
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            doc = None
        if rr_text_parser.json_rr_values(doc) is not None:
            return "json"
        raise UnsupportedFormat(
            "JSON structure not recognised (expected data[].ecg or data[].heartRate)"
        )
    try:
        text = window.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        text = ""
    if text and csv_parser.looks_like(text):
        return "csv"
    if text and rr_text_parser.looks_like_text(text):
        rr_text_parser.parse_text(raw)  # cheap: surface column/unit problems at upload time
        return "csv"
    if _looks_hex(raw):
        raise UnsupportedFormat(
            "Sensor HEX files are not supported yet: their format specification "
            "(docs/sensor-formats.md) has not been provided"
        )
    raise UnsupportedFormat(f"File format not recognised. Supported: {SUPPORTED_DESCRIPTION}")
