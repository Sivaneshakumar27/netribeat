"""HRV constants, with their source (design-spec §6 and backend-stories P4/P5)."""

from __future__ import annotations

# --- design-spec §6 -------------------------------------------------------------
ARTEFACT_WINDOW_BEATS = 11  # local median window (centred; truncated at the ends)
ARTEFACT_THRESHOLD = 0.20  # > 20 % from the local median
PNNI_THRESHOLDS_MS = (20.0, 50.0)
PSD_F_MIN, PSD_F_MAX, PSD_F_STEP = 0.002, 0.5, 0.002
BANDS_HZ = {"vlf": (0.0033, 0.04), "lf": (0.04, 0.15), "hf": (0.15, 0.4)}

# --- provisional (backend-stories) ------------------------------------------------
P4_RR_RANGE_MS = (250.0, 2500.0)  # P4: RR outside → artefact, replaced like others
P5_RESP_WINDOW_S, P5_RESP_STEP_S = 120.0, 60.0  # P5: per-minute respiratory rate
RESP_WINDOW_MIN_BEATS = 30
