"""Helpers shared by the metric files. Ported from lib-netrin."""

import numpy as np
import pandas as pd

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


def durations_s(timestamps):
    """Seconds from each row to the next; the last row gets the median step."""
    t = pd.Series(timestamps).reset_index(drop=True)
    if len(t) == 0:
        return np.array([])
    if len(t) == 1:
        return np.array([float(BUCKET_S)])
    steps = (t.shift(-1) - t).dt.total_seconds().to_numpy(copy=True)
    steps[-1] = np.median(steps[:-1])
    return steps
