"""Movement load and intensity from the accelerometer RMS.

Port of lib-netrin `time_series/rms.py` (`compute_average_rms`, decay 0.9 in svc-sessions
`algo/pipeline.py`) and svc-sessions `algo/metrics/movement.py`.

    RMS per 250 ms -> exponential smoothing (0.9) -> mean per 3 s -> gaps filled from neighbours
    load = Σ RMS · seconds / 3600 (RMS-hours) · intensity = load per hour of recording
"""

import numpy as np

from netribeat.engine.algo.common import bucket, durations_s, exp_decay

RMS_DECAY = 0.9
SECONDS_PER_HOUR = 3600


def rms_time_series(rms, decay=RMS_DECAY):
    """`rms`: DataFrame (timestamp, value), NaN where data was lost. One value per 3 s bucket."""
    rms = rms.sort_values("timestamp", kind="stable")
    rms = rms.assign(value=exp_decay(rms["value"], decay))
    series = bucket(rms, "mean")
    series["value"] = series["value"].ffill().bfill()
    return series


def movement_metrics(rms_series):
    """Movement load and intensity from the 3 s RMS series."""
    if len(rms_series) == 0:
        return {"movement_load": np.nan, "movement_intensity": np.nan}
    seconds = durations_s(rms_series["timestamp"])
    load = round(float((rms_series["value"].to_numpy() * seconds).sum()) / SECONDS_PER_HOUR, 3)
    intensity = round(SECONDS_PER_HOUR * load / seconds.sum(), 3)
    return {"movement_load": load, "movement_intensity": intensity}
