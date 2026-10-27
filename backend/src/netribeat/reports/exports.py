"""CSV and JSON exports built only from stored results (no formulas re-implemented)."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

# Reports take any objects with the expected attributes (the analysis models plug in later).
type Session = Any
type AnalysisResult = Any
type SessionFile = Any

CSV_DATASETS = ("metrics", "hr", "rr", "psd")


def provenance(
    session: Session, result: AnalysisResult, files: list[SessionFile], generated_at: datetime
) -> dict[str, Any]:
    return {
        "analysisVersion": result.analysis_version,
        "analysedAt": session.processed_at.isoformat() if session.processed_at else None,
        "generatedAt": generated_at.isoformat(),
        "sourceFiles": [
            {"name": f.name, "sha256": f.sha256, "format": f.format, "sizeBytes": f.size_bytes}
            for f in files
        ],
        "provisionalRules": result.metrics.get("provisionalRules", {}),
        "methodology": "design-spec §6; see docs/analysis.md",
    }


def session_meta(session: Session) -> dict[str, Any]:
    return {
        "sessionId": str(session.id),
        "type": session.type.value,
        "device": session.device.value,
        "recordedAt": session.recorded_at.isoformat(),
        "recordedAtSource": session.recorded_at_source.value,
        "ageAtRecording": session.age,
        "ageSource": session.age_source.value,
        "hrMaxOverride": session.hr_max_manual,
        "notes": session.notes,
    }


def to_json(
    session: Session, result: AnalysisResult, files: list[SessionFile], generated_at: datetime
) -> bytes:
    doc = {
        "session": session_meta(session),
        "metrics": result.metrics,
        "signals": result.signals,
        "provenance": provenance(session, result, files, generated_at),
    }
    return json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8")


def _flatten(prefix: str, value: Any, rows: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, rows)
    elif isinstance(value, list):
        if len(value) <= 4 and all(not isinstance(v, dict | list) for v in value):
            rows.append((prefix, ";".join("" if v is None else str(v) for v in value)))
    else:
        rows.append((prefix, "" if value is None else str(value)))


def to_csv(session: Session, result: AnalysisResult, dataset: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    s = result.signals
    if dataset == "metrics":
        w.writerow(["metric", "value"])
        rows: list[tuple[str, str]] = []
        _flatten("session", session_meta(session), rows)
        metrics = {k: v for k, v in result.metrics.items() if k != "frequencyDomain"}
        fd = result.metrics.get("frequencyDomain")
        if fd:
            metrics["frequencyDomain"] = {
                k: v for k, v in fd.items() if k not in ("freqs", "power")
            }
        _flatten("", metrics, rows)
        w.writerows(rows)
    elif dataset == "hr":
        w.writerow(["t_s", "hr_bpm"])
        hr = s.get("hr", {})
        w.writerows(zip(hr.get("tS", []), hr.get("bpm", []), strict=False))
    elif dataset == "rr":
        w.writerow(["beat", "t_s", "rr_raw_ms", "rr_corrected_ms", "artefact"])
        flagged = set(s.get("artefactIndices", []))
        triples = zip(
            s.get("beatTimesS", []), s.get("rrRawMs", []), s.get("rrCorrectedMs", []), strict=False
        )
        for i, (t, raw, cor) in enumerate(triples):
            w.writerow([i, t, raw, cor, int(i in flagged)])
    elif dataset == "psd":
        w.writerow(["freq_hz", "power_ms2_per_hz"])
        fd = result.metrics.get("frequencyDomain") or {}
        w.writerows(zip(fd.get("freqs", []), fd.get("power", []), strict=False))
    else:
        raise ValueError(dataset)
    return buf.getvalue().encode("utf-8")
