# Dataset audit (Phase 0)

Source: `Datasets-20261022T060339Z-1-001.zip`. Every figure below was **measured from the
files** by a script, not assumed. Parsers are built in Task 6.

## Individuals and files

The folders D1, D2, D3, D4 and D6 are five separate individuals. **D5 is absent.** The import
(Task 7) will accept any `D<n>` folder without code changes and never invents data.
Every file is treated as its own recording. No file contains metadata linking an ECG
file to an RR file. Durations suggest pairs (D1BL ECG ≈ D1BL HR ≈ 305 s; D1PM ≈ 1283 s;
D2 ≈ 454 s), but they stay separate unless pairing is confirmed.

| File | Kind | Records / rows | Samples or beats | Duration | Sampling | Notes |
|---|---|---|---|---|---|---|
| D1/D1BLECG.json | ECG (JSON) | 9539 packets × 16 | 152624 samples | 305.2 s | 500.0 Hz (fit 32.000 ms/packet) | values -3237…3394, unit undocumented; no packet loss |
| D1/D1BLHR.json | RR (JSON) | 376 | 376 RR | 305.8 s (ΣRR) | beat-to-beat | RR 616–1136 ms, all multiples of 8: True; 0 outside 250–2500 ms; sensor `average` 65.4–89.3 bpm; no timestamps |
| D1/D1PMECG.json | ECG (JSON) | 40087 packets × 16 | 641392 samples | 1283.5 s | 499.7 Hz (fit 32.021 ms/packet) | values -113816…113785, unit undocumented; 6 packet-loss gaps totalling 769 ms; 9 bunched timestamps |
| D1/D1PMHR.json | RR (JSON) | 2121 | 2121 RR | 1283.1 s (ΣRR) | beat-to-beat | RR 264–4024 ms, all multiples of 8: True; 7 outside 250–2500 ms; sensor `average` 89.9–226.7 bpm; no timestamps |
| D2/D2BLECG.json | ECG (JSON) | 14186 packets × 16 | 226976 samples | 453.9 s | 500.0 Hz (fit 32.000 ms/packet) | values -1484…710, unit undocumented; no packet loss |
| D2/D2BLHRjson.json | RR (JSON) | 472 | 472 RR | 453.7 s (ΣRR) | beat-to-beat | RR 280–1272 ms, all multiples of 8: True; 0 outside 250–2500 ms; sensor `average` 55.3–72.9 bpm; no timestamps |
| D3/D3BLHRV _ BLHR.csv | ECG (CSV) | 60944 rows | 60944 samples | 304.7 s | 200.0 Hz | -4.11…4.11 mV (declared); timestamps rounded to 1 ms |
| D4/D4BLHRV _ BLHR.csv | ECG (CSV) | 81808 rows | 81808 samples | 409.0 s | 200.0 Hz | -0.49…0.44 mV (declared); timestamps rounded to 1 ms |
| D4/D4CHRV _ CHR.csv | ECG (CSV) | 853440 rows | 853440 samples | 4267.2 s | 200.0 Hz | -0.92…0.52 mV (declared); timestamps rounded to 1 ms |
| D6/D6BLHRV _ BLHR.csv | ECG (CSV) | 63120 rows | 63120 samples | 315.6 s | 200.0 Hz | -2.88…2.25 mV (declared); timestamps rounded to 1 ms |

## Formats

**JSON ECG** (`data[].ecg.{Timestamp, Samples[16]}`)
- `Timestamp` is in milliseconds. A linear fit gives **exactly 32.000 ms per 16-sample
  packet**, so the rate is **500 Hz**, validated on D1BL and D2BL with residuals under 1 ms
  over 300+ s. The rate was derived from the timestamps, not from the packet size.
- The sample unit is **undocumented**: integers with a range that differs by about 35×
  between files. Values are kept as raw units and never labelled mV. (Question for the
  product owner.)
- D1PMECG shows two timestamp effects that must be told apart:
  - **Bunching:** repeated timestamps followed by a doubled interval. There is no data
    loss; the residual returns to its baseline.
  - **Packet loss:** the residual steps up permanently. There are 6 such gaps,
    totalling 769 ms.
  The planned rule: a gap exists where the residual exceeds its running maximum by
  more than half a packet (16 ms). RR intervals are never computed across a gap.

**JSON RR** (`data[].heartRate.{rrData[], average}`)
- One RR value per record, in **milliseconds**. Confirmed: ΣRR matches the paired ECG
  duration within 0.5 s. All values are multiples of 8 ms, so the resolution is at most
  8 ms.
- `average` is a sensor-computed running heart rate in bpm. It has no timestamps, so it
  can't form a 1 Hz series. It is kept as metadata only.
- D1PMHR has 7 values above 2500 ms (maximum 4024 ms). Whether these are artefacts is
  the P4 decision.
- The JSON files carry **no recording date and no age**. The admin supplies them at import.

**CSV ECG (Movesense)**: comment header, then `"Elapsed time","ECG"`
- The header holds `created` (UTC), `device`, `serial`, `bandwidth` (10–33 Hz), `gender`,
  `age` and units (`s`, `mV`).
- The rate is **200 Hz**: the linear fit is exact, and 4 ms / 6 ms steps are just
  rounding to 1 ms. There are no gaps. Line endings are CRLF.
- Kept: `created`, `device`, `bandwidth`, `age`, units. **Discarded** under CLAUDE.md
  data minimisation: `serial`, `gender`.
- D3 reaches ±4.11 mV in **a single sample**. That is not clipping but one large spike,
  and it defeats the global-max R-peak threshold (see docs/analysis.md).

**Not present:** HEX files, accelerometer data, 1 Hz HR series. Movement load can't be
computed for any supplied file. HEX stays "unsupported format" until
`docs/sensor-formats.md` (missing from the archive) is supplied.
