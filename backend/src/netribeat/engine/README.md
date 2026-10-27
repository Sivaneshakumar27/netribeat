# NetriBeat compute engine

Turns sensor files into time series for analysis. Today: the Synapse hex decoder.

```
engine/
├── decode_hex.py          hex file → RR, HR, RMS and step time series
├── analyse.py             hex file (or decoded CSV) + user profile → metrics
├── derived_metrics/       svc-sessions method (lib-netrin), one file per metric
│   ├── heart_rate.py      3 s HR series; session min / avg / max HR
│   ├── training_load.py   HR zones, time in zones, Banister TRIMP, training intensity
│   ├── movement_load.py   3 s RMS series; movement load and intensity
│   └── common.py          3 s buckets, exponential smoothing, durations
└── tests/
    ├── factories.py       builds synthetic hex files
    ├── test_decode_hex.py
    └── test_derived_metrics.py   expected values from lib-netrin's and svc-sessions' tests
```

```bash
uv run python analyse.py "path/to/NAME_2026-10-22_08_12_39.txt" --age 29 --gender male [--resting-hr 55] [--max-hr 190]
```

Formulas: design-spec §6 (Max HR, Resting HR, HR series, Min / Avg / Max HR, HR zones, Time in
zone, Training load, Movement load).

## Run

```bash
cd engine
uv sync
uv run pytest
uv run python decode_hex.py "path/to/NAME_2026-10-22_08_12_39.txt" --out output/
```

Writes `output/<file name>_session<N>.csv`, one per session, and prints each session's start, end
and RR count. Real recordings are personal data: keep them outside the repo.

From Python:

```python
from decode_hex import decode_hex, start_time_from_filename

sessions = decode_hex(path.read_bytes(), start_time_from_filename(path))  # one DataFrame each
```

## Output

Long format, one row per value: `timestamp, data_item, value`.

| `data_item` | One row per | `value` |
|---|---|---|
| `rrt` | beat | RR from this beat to the next (ms); empty where the next beat is unknown (a break) |
| `hr` | 250 ms slot | 60000 / RR for a beat in that slot (bpm); empty without a beat |
| `rms` | 250 ms slot | accelerometer RMS (sensor units); empty where data was lost |
| `steps` | 7.5 s packet | steps in the packet |

Timestamps are UTC in the DataFrame and IST in the CSV.

**Start time.** The file name `NAME_YYYY-MM-DD_HH_MM_SS` is the recording start in IST. It is
matched to the first session's start packet; the series begin at the first data packet (a few
seconds later). Without a start time, timestamps stay on the sensor clock.

## The hex file

No raw ECG: the sensor detects beats itself and stores RR intervals, accelerometer RMS and step
counts. One packet per line, 200 hex characters:

| Chars | Field |
|---|---|
| 0 | Type: 0 data, 1 restart, 2/3 start (auto/manual), 4/5 stop (auto/manual), 6 resume |
| 1 | Battery 0–10 (× 10 %), on identifier packets |
| 2–9 | Sensor clock, seconds |
| 10–11 | Steps in the packet |
| 12–19 | `FFFFFFFF` |
| 20–199 | 30 samples × 6 chars, one per 250 ms (7.5 s per packet) |

A sample `R M R R M M` holds two 12-bit values: RR in ms (0 = no beat in that slot) and RMS.
`FFF` (4095) means no value. Identifier packets have an all-`F` payload.

## Decoding steps

A port of svc-sessions `src/preprocessing/decode_firmware_data` (v2 layout, firmware ≥ 0.8.0).

1. **Clean the file:** drop invalid lines; of two neighbouring identifier packets of the same type
   keep the second; after a mid-file restart drop what follows if it's ≤ 16 packets; drop
   duplicate lines; drop identifier packets that carry samples.
2. **Split** into sessions from start to stop packet, adding missing starts and stops. Sessions
   without data are ignored.
3. **Per session:**
   - keep data packets only;
   - sort by time and fill gaps over 8.5 s with empty packets (`(gap − 1) // 7.5` of them; one for
     gaps over ~30 min);
   - RR of 4095, or more than 1.9× / less than 0.57× the median of the next 12 RR values → removed;
     sessions with 24 RR values or fewer are skipped;
   - place beats in time from the slot RR values; a lost beat leaves a break.

## Differences from svc-sessions

- **Resume packets are dropped.** svc-sessions kept each as 7.5 s of empty slots, but resume
  packets don't take time: in a field recording they sat between data packets the normal 7.5–8 s
  apart. Measured on a 32-minute recording, packets landed on average 8.3 s (max 9.5 s) from
  their real time with resume slots, and 1.6 s (max 2 s) without.
- **Start time** comes from the file name, not from the app's upload metadata.
- Packets are always sorted by time (svc-sessions: firmware ≥ 0.11.0 only), with a stable sort.
- Invalid lines are skipped instead of crashing the decoder.
- Session duration is end − start, not rounded to a bucket size.

## Verified on a field recording

A 32-minute training recording decodes to one session, 08:12:46–08:44:23 IST: 248 data packets
plus 5 filled, 7,590 HR slots, 3,533 RR values (133 outliers removed, mean RR 489 ms) and 1,846
steps. Packet counts, gaps and steps match an independent decode of the raw file.
