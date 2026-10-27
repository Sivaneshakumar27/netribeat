"""Read an uploaded hex file: decode it into sessions and read the athlete name from the
file name (`NAME_YYYY-MM-DD_HH_MM_SS.txt`)."""

from __future__ import annotations

import re

import pandas as pd

from netribeat.hex_decoder.decode_hex import decode_hex, start_time_from_filename


class ProcessingError(Exception):
    """A user-facing reason the file can't be analysed."""


_NAMED_FILE = re.compile(r"^(?P<name>.+?)_\d{4}-\d{2}-\d{2}_\d{2}_\d{2}_\d{2}$")


def name_from_filename(file_name: str) -> str | None:
    """The athlete name in `NAME_YYYY-MM-DD_HH_MM_SS.txt`, or None for other file names."""
    stem = file_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    m = _NAMED_FILE.match(stem)
    return m["name"].replace("_", " ").strip() or None if m else None


def athlete_name(entered: str | None, file_name: str) -> str | None:
    """Entered on upload first, then the file name; None when neither has one."""
    return (entered or "").strip() or name_from_filename(file_name)


def decode(data: bytes, file_name: str, fallback_start_ms: int) -> list[pd.DataFrame]:
    """All sessions in a hex file. The start time comes from the file name when it has one."""
    start_ms = start_time_from_filename(file_name) or fallback_start_ms
    try:
        sessions: list[pd.DataFrame] = decode_hex(data, start_ms)
    except UnicodeDecodeError:
        raise ProcessingError("Not a Synapse hex file (the file is not text)") from None
    except ValueError as exc:
        raise ProcessingError(f"Not a usable Synapse hex file: {exc}") from None
    if not sessions:
        raise ProcessingError("The file has no session long enough to analyse")
    return sessions
