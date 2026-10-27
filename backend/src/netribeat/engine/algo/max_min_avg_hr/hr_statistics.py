"""Session max / min / average HR from the smoothed HR values.

Port of lib-netrin `metrics/heart_rate.py`.
"""

import numpy as np

from netribeat.engine.algo.hr.heart_rate import MAX_HR, MIN_HR


def plausible(hr):
    hr = np.asarray(hr, dtype=float)
    return hr[(hr >= MIN_HR) & (hr <= MAX_HR)]


def max_hr(hr):
    """Highest HR in a stable stretch: 3 values in a row within 5 bpm, so spikes don't count."""
    hr = plausible(hr)
    windows = np.lib.stride_tricks.sliding_window_view(hr, 3)
    stable = np.concatenate([[False], windows.max(axis=1) - windows.min(axis=1) < 5, [False]])
    return round(float(hr[stable].max()), 3)


def min_hr(hr):
    """1st percentile, so a few low outliers don't count."""
    return round(float(np.percentile(plausible(hr), 1)), 3)


def avg_hr(hr):
    return round(float(np.mean(plausible(hr))), 3)


def hr_metrics(hr):
    """Session max / min / average HR from the smoothed HR values."""
    return {"max_hr": max_hr(hr), "min_hr": min_hr(hr), "avg_hr": avg_hr(hr)}
