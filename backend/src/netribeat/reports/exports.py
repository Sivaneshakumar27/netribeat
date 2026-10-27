"""JSON and CSV exports built only from stored results (no formula is recomputed here)."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

from netribeat.recordings.models import Recording

CSV_DATASETS = ("metrics", "hr", "rr", "rms")


def session_meta(rec: Recording) -> dict[str, Any]:
    return {
        "sessionId": str(rec.id),
        "type": rec.type,
        "device": rec.device,
        "recordedAt": rec.recorded_at.isoformat(),
        "recordedAtSource": rec.recorded_at_source,
        "durationS": rec.duration_s,
        "ageAtRecording": rec.age,
        "hrMaxOverride": rec.hr_max_manual,
        "notes": rec.notes,
        "fileName": rec.file_name,
        "sessionInFile": rec.part + 1,
    }


def to_json(rec: Recording, generated_at: datetime) -> bytes:
    doc = {
        "session": session_meta(rec),
        "metrics": rec.metrics,
        "signals": rec.signals,
        "generatedAt": generated_at.isoformat(),
    }
    return json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8")


def _flatten(prefix: str, value: Any, rows: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, rows)
    elif not isinstance(value, list):
        rows.append((prefix, "" if value is None else str(value)))


def to_csv(rec: Recording, dataset: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    s = rec.signals or {}
    if dataset == "metrics":
        w.writerow(["metric", "value"])
        rows: list[tuple[str, str]] = []
        _flatten("session", session_meta(rec), rows)
        _flatten("", rec.metrics or {}, rows)
        w.writerows(rows)
    elif dataset == "hr":
        w.writerow(["t_s", "hr_bpm"])
        hr = s.get("hr", {})
        w.writerows(zip(hr.get("tS", []), hr.get("bpm", []), strict=False))
    elif dataset == "rr":
        w.writerow(["beat", "t_s", "rr_ms"])
        pairs = zip(s.get("beatTimesS", []), s.get("rrRawMs", []), strict=False)
        w.writerows((i, t, rr) for i, (t, rr) in enumerate(pairs))
    elif dataset == "rms":
        w.writerow(["t_s", "rms"])
        rms = s.get("rms", {})
        w.writerows(zip(rms.get("tS", []), rms.get("value", []), strict=False))
    return buf.getvalue().encode("utf-8")
