"""Heart rate: a smoothed HR time series.

Port of lib-netrin `time_series/heart_rate` (`process_hr`), called by svc-sessions
`algo/pipeline.py` with 3 s buckets and decay 0.7.

    HR per beat -> capped-step smoothing -> median per 3 s -> exponential smoothing (0.7)
                -> HR outside 28-230 bpm removed
"""

import numpy as np


# Helpers shared with movement_load. Ported from lib-netrin.
BUCKET_S = 3  # lib-netrin get_bucket_size(): metric time series use 3 s buckets


def exp_decay(values, decay):
    """Exponential smoothing that skips NaNs: y = previous · decay + x · (1 − decay).

    Loops because each value depends on the previous smoothed value. Rounded to 2 decimals.
    """
    out = np.array(values, dtype=float)
    valid = np.flatnonzero(~np.isnan(out))
    if valid.size == 0:
        raise ValueError("Input series contains only NaNs")
    prev = out[valid[0]]
    for i in valid[1:]:
        out[i] = prev = prev * decay + out[i] * (1 - decay)
    return np.round(out, 2)


def bucket(df, agg, seconds=BUCKET_S):
    """Aggregate `value` per time bucket (timestamps floored to multiples of `seconds`)."""
    floored = df.assign(timestamp=df["timestamp"].dt.floor(f"{seconds}s"))
    return floored.groupby("timestamp", as_index=False)["value"].agg(agg)


HR_DECAY = 0.7
MIN_HR, MAX_HR = 28, 230  # plausible HR range (bpm)


def smoothen_outliers(values):
    """Follow the HR in capped steps, so single wrong beats can't jump the value.

    Starts at the median of the first 10 beats; then moves toward each new value by 0, 1, 2 or
    3 bpm depending on how far away it is (only 1 bpm for jumps of 30+, likely artefacts).
    Loops because each step depends on the previous value.
    """
    current = round(float(np.median(values[:10])), 2)
    out = np.empty(len(values))
    for i, value in enumerate(values):
        diff = abs(value - current)
        step = 0 if diff < 1 else 1 if diff < 3 else 2 if diff < 10 else 3 if diff < 30 else 1
        current += step * np.sign(value - current)
        out[i] = current
    return out


def hr_time_series(hr, decay=HR_DECAY):
    """`hr`: DataFrame (timestamp, value) of HR per beat or slot, NaN where there is no beat.

    Returns one smoothed HR per 3 s bucket (svc-sessions' `corrected_hr_avg`), NaN where the
    result is outside 28-230 bpm.
    """
    hr = hr.dropna(subset=["value"]).sort_values("timestamp", kind="stable")
    hr = hr.assign(value=smoothen_outliers(hr["value"].to_numpy()))
    series = bucket(hr, "median")
    series["value"] = exp_decay(series["value"], decay)
    series.loc[(series["value"] < MIN_HR) | (series["value"] > MAX_HR), "value"] = np.nan
    if series["value"].isna().all():
        raise ValueError("No valid HR detected")
    return series
