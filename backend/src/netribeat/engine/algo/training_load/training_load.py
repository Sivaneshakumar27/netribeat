"""Training load: HR zones, time in each zone, TRIMP training load and training intensity.

Port of lib-netrin `time_series/hr_zone.py`, `users/user_thresholds.py`,
`metrics/training_load.py` and `metrics/training_metrics.py`. Input is the smoothed HR series
from heart_rate.hr_time_series().
"""

import numpy as np

from netribeat.engine.algo.common import durations_s

DEFAULT_RESTING_HR = 50  # lib-netrin get_default_min_hr()
ZONE_FRACTIONS = [0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]  # zone 0-6 lower bounds, fraction of max HR
GENDER_FACTOR = {"male": 1.92, "female": 1.67}  # Banister TRIMP weighting


def theoretical_max_hr(age):
    """Default max HR when none is set (lib-netrin compute_theoretical_max_hr)."""
    return 210 - 0.65 * age


def zone_thresholds(max_hr, resting_hr=DEFAULT_RESTING_HR, formula="classic"):
    """Lower HR bound of zones 0-6.

    classic: fraction of max HR. heart_rate_reserve: fraction of (max − resting) above resting.
    """
    if formula == "classic":
        return [f * max_hr for f in ZONE_FRACTIONS]
    if formula == "heart_rate_reserve":
        return [0] + [f * (max_hr - resting_hr) + resting_hr for f in ZONE_FRACTIONS[1:]]
    raise ValueError(f"Unknown zone formula: {formula}")


def hr_zones(hr, thresholds):
    """Zone 0-5 per HR value: the highest zone whose lower bound the HR reaches.

    Above max HR counts as zone 5; NaN HR counts as zone 0, as in lib-netrin.
    """
    hr = np.asarray(hr, dtype=float)
    zones = np.zeros(len(hr), dtype=int)
    for zone, lower in enumerate(thresholds):
        zones[hr >= lower] = zone
    return np.minimum(zones, 5)


def zone_durations_ms(timestamps, zones):
    """Milliseconds spent in each zone 0-5."""
    seconds = durations_s(timestamps)
    return {str(z): int(seconds[np.asarray(zones) == z].sum() * 1000) for z in range(6)}


def training_load(timestamps, hr, resting_hr, max_hr, gender):
    """Banister TRIMP: Σ minutes · r · 0.64 · e^(k·r), r = (HR − resting) / (max − resting).

    k = 1.92 for men, 1.67 for women. HR below resting adds nothing. Resting and max HR are
    truncated to whole bpm, as in lib-netrin.
    """
    if gender not in GENDER_FACTOR:
        raise ValueError(f"Training load needs gender male or female, got {gender!r}")
    resting, maximum = int(resting_hr), int(max_hr)
    r = (np.asarray(hr, dtype=float) - resting) / (maximum - resting)
    trimp = durations_s(timestamps) / 60 * r * 0.64 * np.exp(GENDER_FACTOR[gender] * r)
    trimp[trimp < 0] = 0
    return round(float(np.nansum(trimp)), 3)


def training_intensity(timestamps, load):
    """Training load per minute of recording."""
    seconds = durations_s(timestamps)
    if seconds.size == 0:
        return 0
    return round(load / (seconds.sum() / 60), 3)


def training_metrics(hr_series, max_hr, resting_hr, gender, formula="classic"):
    """All training metrics from the smoothed HR series (DataFrame timestamp, value)."""
    times, hr = hr_series["timestamp"], hr_series["value"]
    zones = hr_zones(hr, zone_thresholds(max_hr, resting_hr, formula))
    load = training_load(times, hr, resting_hr, max_hr, gender)
    return {
        "hr_zone_durations": zone_durations_ms(times, zones),
        "training_load": load,
        "training_intensity": training_intensity(times, load),
    }
