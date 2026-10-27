"""Metrics derived from a decoded session: heart rate, training load, movement load.

Port of the svc-sessions method (lib-netrin). One file per metric:

    heart_rate.py      smoothed HR series (3 s), session min / average / max HR
    training_load.py   HR zones, time in zones, Banister TRIMP, training intensity
    movement_load.py   smoothed RMS series (3 s), movement load and intensity
    common.py          3 s buckets, exponential smoothing, per-row durations
"""
