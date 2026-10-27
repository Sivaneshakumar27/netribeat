"""Heart rate, training load and movement load for one decoded session (reference engine,
`analyse_session` unchanged). Max HR defaults to 210 − 0.65 · age and resting HR to 50 bpm."""

from netribeat.engine.algo.hr.heart_rate import hr_time_series
from netribeat.engine.algo.max_min_avg_hr.hr_statistics import hr_metrics
from netribeat.engine.algo.movement_load.movement_load import movement_metrics, rms_time_series
from netribeat.engine.algo.training_load.training_load import (
    DEFAULT_RESTING_HR,
    theoretical_max_hr,
    training_metrics,
)


def item(df, name):
    return df.loc[df["data_item"] == name, ["timestamp", "value"]].reset_index(drop=True)


def analyse_session(df, age, gender, max_hr=None, resting_hr=None, zones="classic"):
    """`df`: one decoded session (timestamp, data_item, value). Returns all metrics."""
    max_hr = max_hr or theoretical_max_hr(age)
    resting_hr = resting_hr or DEFAULT_RESTING_HR
    hr = hr_time_series(item(df, "hr"))
    rms = rms_time_series(item(df, "rms"))
    return {
        "hr_metrics": hr_metrics(hr["value"]),
        "training_metrics": training_metrics(hr, max_hr, resting_hr, gender, zones),
        "movement_metrics": movement_metrics(rms),
    }
