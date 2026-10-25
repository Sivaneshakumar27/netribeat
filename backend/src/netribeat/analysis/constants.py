"""Every analysis constant, with its source. design-spec §6 values are authoritative.
Values marked PROVISIONAL come from backend-stories P2–P5 proposals that the product
owner has not yet settled; they are reported as provisional in every result."""

from __future__ import annotations

ANALYSIS_VERSION = "1.0.0"

# --- design-spec §6 -------------------------------------------------------------
HRMAX_AGE_BASE = 210  # age method: 210 − age
HRMAX_MANUAL_RANGE = (100, 230)
ZONE_EDGES_PCT = (50.0, 60.0, 70.0, 80.0, 90.0)  # Z1 50–60 … Z5 ≥ 90; below Z1 < 50
PT_INTEGRATION_S = 0.150  # Pan–Tompkins moving-integration window
PT_THRESHOLD_FRACTION = 0.3  # threshold = 0.3 × max of the integrated signal
PT_REFRACTORY_S = 0.250
ARTEFACT_WINDOW_BEATS = 11  # local median window (centred; truncated at the ends)
ARTEFACT_THRESHOLD = 0.20  # > 20 % from the local median
HRV_WINDOW_S = 300.0  # first 5 min of the corrected RR series
PNNI_THRESHOLDS_MS = (20.0, 50.0)
PSD_F_MIN, PSD_F_MAX, PSD_F_STEP = 0.002, 0.5, 0.002
BANDS_HZ = {"vlf": (0.0033, 0.04), "lf": (0.04, 0.15), "hf": (0.15, 0.4)}
QUALITY_MIN_RR = 30  # < 30 RR intervals → no_ecg
QUALITY_POOR_ARTEFACT_PCT = 5.0  # > 5 % artefacts → poor
MOVEMENT_LOAD_DIVISOR = 100.0

# --- PROVISIONAL (backend-stories, not yet settled) -------------------------------
P2_MAX_MISSING_FRACTION = 0.10  # P2: split at gaps; > 10 % missing fails
P3_HR_GRID_S = 1.0  # P3: 1 Hz HR = linear interpolation of corrected beat HR
P4_RR_RANGE_MS = (250.0, 2500.0)  # P4: RR outside → artefact, replaced like others
P5_RESP_WINDOW_S, P5_RESP_STEP_S = 120.0, 60.0  # P5: per-minute respiratory rate
PROVISIONAL_RULES = {
    "P2": "ECG split into segments at recording gaps; RR never computed across a gap; "
    "> 10 % missing samples fails the recording",
    "P3": "1 Hz heart rate = linear interpolation of corrected beat HR onto a 1 s grid",
    "P4": "RR intervals outside 250–2500 ms are flagged as artefacts and replaced by the "
    "local median",
    "P5": "Per-minute respiratory rate = HF peak × 60 of a 2-minute window, stepped 1 minute",
}

# --- implementation decisions (not in the spec; documented in docs/analysis.md) ----
HRV_MIN_BEATS = 30  # same floor as the no_ecg rule; fewer → HRV metrics unavailable
RESP_WINDOW_MIN_BEATS = 30
ECG_STRIP_S = 10.0
# Beat coverage = Σ unflagged RR / recording duration. On the supplied data, recordings
# whose detection agrees with the sensor's own RR have ≥ 0.88; failed detections (motion
# spikes defeating the global 0.3 × max threshold) have ≤ 0.60. Below this value every
# result carries a "detection unreliable" warning. design-spec §6 quality is unchanged.
MIN_BEAT_COVERAGE = 0.80
