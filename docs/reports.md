# Reports & exports

What you can download for a session, and where each number comes from. Code:
`backend/src/netribeat/reports/`.

[← Back to README](../README.md)

---

All downloads are built from the **stored** results — nothing is recalculated when you download,
so the PDF, the exports and the screen always agree. Missing values print as **—**.

| Download | Endpoint | Button on the session page |
|---|---|---|
| PDF report | `GET /sessions/{id}/report` | *PDF report* |
| Everything as JSON | `GET /sessions/{id}/export.json` | *JSON (all results)* |
| Metrics table | `GET /sessions/{id}/export.csv?dataset=metrics` | *CSV metrics* |
| Heart rate series | `…?dataset=hr` | *CSV heart rate* |
| Beats | `…?dataset=rr` | *CSV beats* |
| Movement series | `…?dataset=rms` | — (API only) |
| Original hex file | `GET /sessions/{id}/files/{fileId}` | *Original file* |

## PDF report — `pdf.py`

Two A4 pages in the NetriBeat style: black header band with the logo, orange accents, light pages.
Drawn with matplotlib. The header shows the session type and date — never the account holder's name.

**Athlete name:** the *Athlete name* field on upload → the name in the file name
(`BOOPATHI R_2026-10-22_08_12_39.txt` → *BOOPATHI R*) → **—**.

### Page 1 · HRV Analysis Report

| Block | Shows |
|---|---|
| Subject | Athlete name, age, gender, height, weight, BMI, resting HR, max HR used, session type, recorded (IST), duration, HRV sample window |
| RR intervals | Whole tachogram; analysed sample shaded; corrected beats as orange dots |
| Time domain | Mean RR, SDNN, Mean HR, SD HR, Min/Max HR, RMSSD, NN50, pNN50, RR triangular index, TINN, Stress index |
| RR histogram · Poincaré plot | Distribution of RR; RR(n) vs RR(n+1) with the SD1/SD2 ellipse |
| Frequency domain | VLF / LF / HF for **Welch FFT** and **AR**: peak Hz, ms², %, n.u.; total; LF/HF — plus the power spectrum |
| Nonlinear | SD1/SD2, SD2/SD1, ApEn, SampEn, DFA α1/α2, recurrence REC/DET |
| Autonomic balance | Parasympathetic (Mean RR, RMSSD, SD1 share) and sympathetic (Mean HR, Stress index, SD2 share) |
| DFA plot | log F(n) vs log n for α1 and α2 |

### Page 2 · Session & Training Report

| Block | Shows |
|---|---|
| Summary tiles | Average / max / min HR (with % of max HR), max HR used, training load, training intensity, movement load, steps and respiratory rate |
| Heart rate over time | Smoothed HR on a background coloured by zone |
| Time in zones | Bar per zone with time and share |
| HRV over time | RMSSD and mean HR in 60 s windows |
| Movement | Accelerometer RMS (3 s) |
| Respiratory rate | Breaths per minute, minute by minute |

If zones or training load can't be computed (no age / no gender), the tile shows "—" and a note
says what to enter.

## JSON export — `exports.py`

```json
{
  "session":   { "sessionId": "…", "type": "training", "recordedAt": "…", "durationS": 1500, "fileName": "…", "sessionInFile": 1, … },
  "metrics":   { … everything in recordings.metrics … },
  "signals":   { … every series … },
  "generatedAt": "…"
}
```

Field meanings: [Processing → What gets stored](processing.md#7--what-gets-stored).

## CSV exports

| `dataset` | Columns |
|---|---|
| `metrics` | `metric, value` — every scalar result, flattened (`session.*`, `hr.avg`, `advanced.timeDomain.rmssd`, …) |
| `hr` | `t_s, hr_bpm` — smoothed HR, seconds from the start |
| `rr` | `beat, t_s, rr_ms` |
| `rms` | `t_s, rms` |
