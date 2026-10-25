"""Normalised parser output. Pure data: no database, no FastAPI, no filesystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


class SignalKind(StrEnum):
    ECG = "ecg"
    RR = "rr"


class ParserError(Exception):
    """The file is recognised but its content is invalid. Message is user-safe."""


class UnsupportedFormat(ParserError):
    """No parser recognises the file."""


@dataclass(frozen=True)
class EcgSegment:
    """Contiguous ECG samples. Segments are separated by recording gaps (P2): R-peaks
    are detected per segment and no RR interval ever spans two segments."""

    start_s: float  # seconds from the start of the recording
    samples: FloatArray


@dataclass
class ParsedRecording:
    format: str  # e.g. "movesense_json_ecg"
    kind: SignalKind
    duration_s: float
    unit: str  # ECG sample unit ("mV", or "raw" when undocumented); "ms" for RR
    fs_hz: float | None = None
    segments: list[EcgSegment] = field(default_factory=list)
    rr_ms: FloatArray | None = None
    missing_fraction: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def sample_count(self) -> int:
        return int(sum(s.samples.size for s in self.segments))
