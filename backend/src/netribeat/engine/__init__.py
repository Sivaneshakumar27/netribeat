"""Synapse hex decoder and derived metrics, copied unchanged from references/ (SES-4, SES-7).

The engine files import each other as top-level modules (`from decode_hex import …`,
`from derived_metrics… import …`), as when run as scripts. Putting this folder on the import
path lets the backend use them without editing a line of them.
"""

import sys
from pathlib import Path

_HERE = str(Path(__file__).parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from analyse import analyse_session, item  # noqa: E402
from decode_hex import IST, decode_hex, start_time_from_filename  # noqa: E402
from derived_metrics.heart_rate import hr_metrics, hr_time_series  # noqa: E402
from derived_metrics.movement_load import movement_metrics, rms_time_series  # noqa: E402
from derived_metrics.training_load import (  # noqa: E402
    DEFAULT_RESTING_HR,
    hr_zones,
    theoretical_max_hr,
    zone_durations_ms,
    zone_thresholds,
)

__all__ = [
    "DEFAULT_RESTING_HR",
    "IST",
    "analyse_session",
    "decode_hex",
    "hr_metrics",
    "hr_time_series",
    "hr_zones",
    "item",
    "movement_metrics",
    "rms_time_series",
    "start_time_from_filename",
    "theoretical_max_hr",
    "zone_durations_ms",
    "zone_thresholds",
]
