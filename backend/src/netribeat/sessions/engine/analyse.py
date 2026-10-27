"""Compute heart rate, training load and movement load for a recording.

    python analyse.py "NAME_2026-10-22_08_12_39.txt" --age 29 --gender male
    python analyse.py output/NAME_session1.csv --age 29 --gender female --resting-hr 55

Input: a Synapse hex file, or a session CSV written by decode_hex.py. Max HR defaults to
210 − 0.65 · age and resting HR to 50 bpm, as in svc-sessions.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from decode_hex import decode_hex, start_time_from_filename
from derived_metrics.heart_rate import hr_metrics, hr_time_series
from derived_metrics.movement_load import movement_metrics, rms_time_series
from derived_metrics.training_load import DEFAULT_RESTING_HR, theoretical_max_hr, training_metrics


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


def load_sessions(path):
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return [df]
    return decode_hex(path.read_bytes(), start_time_from_filename(path))


def main():
    parser = argparse.ArgumentParser(description="Compute session metrics")
    parser.add_argument("file", type=Path, help="hex file, or a session CSV from decode_hex.py")
    parser.add_argument("--age", type=int, required=True)
    parser.add_argument("--gender", choices=["male", "female"], required=True)
    parser.add_argument("--max-hr", type=float, help="default: 210 − 0.65 · age")
    parser.add_argument("--resting-hr", type=float, help=f"default: {DEFAULT_RESTING_HR}")
    parser.add_argument("--zones", choices=["classic", "heart_rate_reserve"], default="classic")
    args = parser.parse_args()

    sessions = load_sessions(args.file)
    results = [
        analyse_session(df, args.age, args.gender, args.max_hr, args.resting_hr, args.zones)
        for df in sessions
    ]
    print(json.dumps(results, indent=2))
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
