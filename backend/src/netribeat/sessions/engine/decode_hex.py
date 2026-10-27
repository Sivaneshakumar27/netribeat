"""Decode a Synapse sensor hex file into RR, HR, RMS and step time series.

Port of svc-sessions `decode_firmware_data` (v2 layout).

    python decode_hex.py "NAME_2026-10-22_08_12_39.txt"

One packet per line, 200 hex chars:
    [0] type: 0 data, 1 restart, 2/3 start, 4/5 stop, 6 resume
    [2:10] sensor time (s) · [10:12] steps · [20:200] 30 samples, one per 250 ms
    sample "RMRRMM": RR in ms (0 = no beat) and accelerometer RMS, 12 bits each; 4095 = none
"""

import argparse
import itertools
import re
import sys
from datetime import timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SLOT_MS = 250
PACKET_S = 7.5
NO_VALUE = 4095
IST = timezone(timedelta(hours=5, minutes=30))


# ------------------------------------------------------------------ clean the file


def remove_invalid_lines(lines):
    return [line for line in lines if re.fullmatch("[0-7][0-9A-F]{199}", line)]


def remove_repeated_identifiers(lines):
    """Of two neighbouring identifier packets of the same type, keep the second."""
    return [a for a, b in itertools.pairwise(lines) if not (a[0] == b[0] != "0")] + lines[-1:]


def remove_data_after_restart(lines):
    """Keep from the last initial restart; drop what follows a later restart if <= 16 packets."""
    restarts = [i for i, line in enumerate(lines) if line[0] == "1"]
    first = next((i for i in range(10) if i not in restarts), None)
    if first is None:
        raise ValueError("Hex file has only restart packets")
    later = [i for i in restarts if i > first]
    if later and len(lines) - later[0] > 16:
        return lines
    return lines[max(first - 1, 0) : later[0] if later else None]


def remove_corrupt_identifiers(lines):
    """Identifier packets carry no samples; ones with samples are corrupt."""
    return [line for line in lines if not (line[0] in "34567" and line[20:] != "F" * 180)]


def clean(lines):
    lines = remove_invalid_lines(lines)
    if not any(line[0] == "0" for line in lines):
        raise ValueError("Hex file has no data packets")
    lines = remove_repeated_identifiers(lines)
    lines = remove_data_after_restart(lines)
    lines = list(dict.fromkeys(lines))  # remove duplicates, keep order
    return remove_corrupt_identifiers(lines)


# ------------------------------------------------------------------ split into sessions


def kind(line):
    return {"1": "restart", "2": "start", "3": "start", "4": "stop", "5": "stop"}.get(
        line[0], "body"
    )


def marker(type_char, line):
    """A start or stop packet with the battery and time of `line`."""
    return type_char + line[1:10] + "F" * 190


def add_missing_start_stop(lines):
    kinds = [kind(line) for line in lines]
    out = []
    for i, line in enumerate(lines):
        prev = kinds[i - 1]  # wraps to the last line for i == 0, as in svc-sessions
        if i > 0 and kinds[i] == "start" and prev not in ("stop", "restart"):
            out.append(marker("4", line))
        elif i < len(lines) - 1 and prev == "stop" and kinds[i] not in ("start", "restart"):
            out.append(marker("2", line))
        out.append(line)
    if kind(out[-1]) != "stop":
        out.append(marker("4", out[-1]))
    if kind(out[0]) == "body":
        out.insert(0, marker("2", out[0]))
    elif kind(out[0]) == "restart" and kind(out[1]) != "start":
        out.insert(1, marker("2", out[0]))
    return out


def split_sessions(lines):
    lines = add_missing_start_stop(lines)
    starts = [i for i, line in enumerate(lines) if kind(line) == "start"]
    stops = [i for i, line in enumerate(lines) if kind(line) == "stop"]
    sessions = [lines[a : b + 1] for a, b in zip(starts, stops)]
    return [s for s in sessions if any(line[0] == "0" for line in s)]


# ------------------------------------------------------------------ signals


def sensor_time(line):
    return int(line[2:10], 16)


def fill_missing_packets(lines):
    """Sort by time; fill gaps over 8.5 s with no-beat packets (one packet for gaps > ~30 min)."""
    lines = sorted(lines, key=sensor_time)
    out = lines[:1]
    for prev, line in itertools.pairwise(lines):
        gap = sensor_time(line) - sensor_time(prev)
        if gap > PACKET_S + 1:
            missing = int((gap - 1) // PACKET_S)
            missing = 1 if missing > 240 else missing
            out += [
                f"FF{round(sensor_time(prev) + j * PACKET_S):08X}00" + "F" * 8 + "0F00FF" * 30
                for j in range(1, missing + 1)
            ]
        out.append(line)
    return out


def read_samples(lines):
    samples = [line[i : i + 6] for line in lines for i in range(20, 200, 6)]
    steps = np.array([int(line[10:12], 16) for line in lines], float)
    rr = np.array([int(s[0] + s[2:4], 16) for s in samples], float)
    rms = np.array([int(s[1] + s[4:6], 16) for s in samples], float)
    rms[rms == NO_VALUE] = np.nan
    return steps, rr, rms


def remove_rr_outliers(rr, window=12):
    """Zero RR above 1.9x or below 0.57x the median of the next 12 RR values."""
    rr = np.where(rr == NO_VALUE, 0, rr)
    beats = rr[rr > 0]
    if len(beats) <= 2 * window:
        raise ValueError(f"Session too short: {len(beats)} RR values")
    median = np.median(np.lib.stride_tricks.sliding_window_view(beats, window), axis=1)
    median = np.append(median, median[-(window - 1) :])
    ratio = beats / median
    beats[(ratio > 1.9) | (ratio < 0.57)] = 0
    rr[rr > 0] = beats
    return rr


def beat_times(rr, start_ms):
    """Place beats from per-slot RR. Returns beat times and RR to the next beat (NaN at breaks).

    An RR matching the empty slots since the last beat places the next beat RR ms later. A
    shorter RR means beats were lost: re-anchor to the slot and leave a break.
    """
    times, values = [start_ms], [np.nan]
    empty, current = 0, start_ms
    for i, value in enumerate(rr):
        if value == 0:
            empty += 1
            continue
        min_gap, max_gap = empty * SLOT_MS, (empty + 2) * SLOT_MS
        if value > max_gap:
            continue  # stray value (at the very start: ignored without resetting)
        if value >= min_gap:
            values[-1] = value
            current += int(value)
            times.append(current)
            values.append(np.nan)
        else:
            current = start_ms + SLOT_MS * (i + 1)
            times += [current - int(value), current]
            values += [value, np.nan]
        empty = 0
    return np.array(times), np.array(values)


def to_series(name, times_ms, values):
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(times_ms, unit="ms", utc=True),
            "data_item": name,
            "value": values,
        }
    )


def decode_session(session, offset_ms):
    # Data packets only: resume packets take no time, so keeping them (as svc-sessions did)
    # would shift every later beat by 7.5 s. Real pauses are filled as missing packets.
    lines = fill_missing_packets([line for line in session[1:-1] if line[0] == "0"])
    start_ms = sensor_time(lines[0]) * 1000 + offset_ms

    steps, rr, rms = read_samples(lines)
    rr = remove_rr_outliers(rr)
    last_beat = np.flatnonzero(rr)[-1]
    slots = start_ms + np.arange(len(rr)) * SLOT_MS
    with np.errstate(divide="ignore"):
        hr = np.round(np.where(rr > 0, 60_000 / rr, np.nan), 3)

    return pd.concat(
        [
            to_series("rrt", *beat_times(rr, start_ms)),
            to_series("hr", slots, hr),
            to_series("rms", slots[: last_beat + 1], rms[: last_beat + 1]),
            to_series("steps", start_ms + np.arange(len(steps)) * int(PACKET_S * 1000), steps),
        ],
        ignore_index=True,
    )


def decode_hex(hex_bytes, start_time_ms=None):
    """Decode a hex file into one DataFrame (timestamp, data_item, value) per session.

    `start_time_ms` is the recording start (UTC epoch ms), matched to the first start packet.
    Without it, times stay on the sensor clock. Sessions too short to analyse are skipped.
    """
    lines = [line.strip().upper() for line in hex_bytes.decode("ascii").splitlines()]
    sessions = split_sessions(clean(lines))
    offset_ms = 0 if start_time_ms is None else start_time_ms - sensor_time(sessions[0][0]) * 1000

    decoded = []
    for session in sessions:
        try:
            decoded.append(decode_session(session, offset_ms))
        except ValueError:
            continue
    return decoded


def start_time_from_filename(path):
    """NAME_YYYY-MM-DD_HH_MM_SS holds the recording start in IST; returns UTC epoch ms."""
    match = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})_(\d{2})$", Path(path).stem)
    if match is None:
        return None
    date, hh, mm, ss = match.groups()
    return int(pd.Timestamp(f"{date} {hh}:{mm}:{ss}", tz=IST).timestamp() * 1000)


def main():
    parser = argparse.ArgumentParser(description="Decode a Synapse hex file")
    parser.add_argument("hex_file", type=Path)
    parser.add_argument("--out", type=Path, default=Path("output"))
    args = parser.parse_args()

    sessions = decode_hex(args.hex_file.read_bytes(), start_time_from_filename(args.hex_file))
    args.out.mkdir(parents=True, exist_ok=True)
    for i, df in enumerate(sessions, start=1):
        path = args.out / f"{args.hex_file.stem}_session{i}.csv"
        df.assign(timestamp=df["timestamp"].dt.tz_convert(IST)).to_csv(path, index=False)
        start, end = df["timestamp"].min().tz_convert(IST), df["timestamp"].max().tz_convert(IST)
        beats = df["value"][df["data_item"] == "rrt"].notna().sum()
        print(f"Session {i}: {start:%Y-%m-%d %H:%M:%S} to {end:%H:%M:%S} IST, {beats} RR -> {path}")
    return 0 if sessions else 1


if __name__ == "__main__":
    sys.exit(main())
