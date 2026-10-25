# Analysis: methods, decisions and validation

All authoritative calculations run on the backend (`backend/src/netribeat/analysis/`),
which is pure Python/NumPy/SciPy with no database or web dependencies. Every constant
lives in `analysis/constants.py` with its source. Results are computed once by the
background worker and stored; screens and exports only read stored results.

## Pipeline

1. **Parse** (`parsers/`): the format is detected from the file's **content**, not its name.
   Text encodings accepted: UTF-8 with or without a BOM, and UTF-16 with a BOM (common for
   files saved by Notepad, Excel or Windows PowerShell 5).
   - Movesense JSON ECG: 500 Hz. The rate is derived from each file's timestamps and
     must be consistent; samples are in raw units because no unit is documented. Gaps
     are detected (below).
   - Movesense JSON RR: `rrData` in ms. The sensor's `average` is kept as metadata only.
   - Movesense CSV ECG: 200 Hz, mV. The header provides age and recording time;
     `serial` and `gender` are discarded.
   - Sensor HEX: explicitly unsupported until `docs/sensor-formats.md` exists.
2. **Beats**: R-peaks per ECG segment; RR intervals are never computed across a gap.
   RR files skip detection.
3. **Artefacts**: the 11-beat local median rule, plus P4.
4. **Quality**: the §6 rule, plus a separate reliability check (below).
5. **1 Hz heart rate** (P3) → min / avg / max.
6. **HRV window**: the first 300 s of the corrected RR series → time domain, Lomb–Scargle
   PSD, Poincaré, respiratory rate.
7. **HRmax → zones → Edwards TRIMP.** This step is applied separately, so a change to
   the HRmax setting recomputes it from the stored 1 Hz series without re-running ECG
   processing. It recomputes **only that user's sessions**.

## design-spec §6, implemented exactly

| Metric | Implementation |
|---|---|
| R-peaks | Derivative → square → 150 ms trailing moving average → threshold 0.3 × max → 250 ms refractory (the larger peak wins) → maximum of the raw signal over the integration window. No other filtering is added. |
| RR / beat HR | RR = Δt between R-peaks (ms); beat HR = 60 000 / RR |
| Artefacts | A beat more than 20 % from the median of its centred 11-beat window (truncated at the ends) is flagged and replaced by that median. Exactly 20 % is not flagged. |
| HRV window | Beats whose time is ≤ 300 s from the recording start |
| RMSSD, pNNI20/50, SDNN | √mean(ΔRR²); % of \|ΔRR\| > 20 / 50 ms (strictly greater than); sample SD (ddof = 1) |
| PSD | `scipy.signal.lombscargle` at 0.002–0.5 Hz in 0.002 Hz steps, scaled so Σ P·Δf = sample variance of RR |
| Bands | VLF [0.0033, 0.04), LF [0.04, 0.15), HF [0.15, 0.4). % of VLF+LF+HF; n.u. = LF or HF / (LF+HF) × 100; peak = the frequency of the highest power in the band. `totalPower` = VLF+LF+HF. |
| Poincaré | SD1 = SD(ΔRR)/√2; SD2 = √(2·SDNN² − SD1²) |
| Respiratory rate | HF peak × 60 |
| HRmax | The user's saved method (age / peak / manual) → else the session's upload override → else 210 − **age at recording** |
| Zones | Below Z1 < 50 %, Z1 [50, 60) … Z5 ≥ 90 % of HRmax, counted from 1 Hz samples |
| Training load | Edwards TRIMP = Σ minutes in zone × zone number (1–5) |
| Quality | `no_ecg` if < 30 RR; `poor` if artefacts > 5 %; else `good` |
| Movement load | The formula is implemented and tested, but no supported input contains accelerometer data, so it is always reported as unavailable, with a reason |

## Provisional rules (backend-stories P2–P5, not yet settled)

Each is applied, listed in every result under `provisionalRules`, printed in the PDF, and
shown on the session page.

- **P2:** split at recording gaps; fail when more than 10 % of samples are missing.
- **P3:** 1 Hz heart rate = linear interpolation of corrected beat HR.
- **P4:** RR outside 250–2500 ms is treated as an artefact.
- **P5:** respiratory rate per minute = HF peak of a 2-minute window, stepped by 1 minute.

## Implementation decisions (not in the spec; please confirm)

| Decision | Why |
|---|---|
| Gap detection for JSON ECG: a gap exists where the timestamp residual rises above its running maximum by more than half a packet | Distinguishes real packet loss from harmless "bunched" timestamps (measured on D1PMECG) |
| HRV needs at least 30 RR intervals in the window | Same floor as the `no_ecg` rule. Recordings shorter than 300 s use the available beats and carry a warning. |
| With quality `no_ecg`, heart rate, zones and load are **unavailable** | Numbers from a handful of beats (e.g. "0.1 bpm") are meaningless |
| **Beat coverage** reliability check: Σ unflagged RR / duration < 0.80 → "detection unreliable" | See below. The §6 quality rule is unchanged. |
| "Peak" HRmax uses only reliable, ready sessions that aren't `no_ecg` | Prevents a failed detection from setting a false peak |
| An age entered at upload wins over the file header's age; a mismatch adds a warning | An explicit entry is the user's intent; the mismatch stays visible |

## Validation on the supplied recordings

Two individuals have both an ECG file and the sensor's own RR file, which gives an
independent check of the R-peak detector:

| | Avg HR, ECG / sensor RR | RMSSD, ECG / sensor RR |
|---|---|---|
| D1 baseline | 73.9 / 74.1 bpm | 67.8 / 68.2 ms |
| D2 baseline | 62.4 / 62.4 bpm | 98.6 / 98.4 ms |

**Known limitation of the specified detector.** Its threshold is 0.3 × the maximum of
the *whole* recording. A single motion spike therefore raises the threshold above every
real beat:

| Recording | Beats found | Beat coverage | Result |
|---|---|---|---|
| D1 post-match ECG | 476 (sensor counted 2121) | 0.21 | flagged unreliable |
| D3 baseline | 0 | 0 | one extreme sample; `no_ecg`, unreliable |
| D4 long recording (71 min) | 6 | 0 | `no_ecg`, unreliable |
| D6 baseline | 251 | 0.60 | flagged unreliable |
| D1/D2/D4 baselines, all RR files | as expected | ≥ 0.88 | reliable |

For the four failures, a detector with an adaptive or segment-wise threshold, and a
band-pass filter (both standard in Pan–Tompkins), would very likely recover the beats.
That would change the §6 definition, so it needs a product-owner decision. Until then,
these recordings are clearly marked unreliable everywhere: the list, the session view,
the PDF and the exports.

## Tests

`tests/unit/test_analysis.py` checks every formula against hand-computed or exactly known
values, every boundary (20 % exactly, 30 RR, 5 %, zone edges), and edge cases (empty,
flat and constant signals, gaps, short recordings). It also runs the golden checks on the
real files, including the ECG-versus-sensor agreement above.
`tests/unit/test_parsers.py` covers every supplied format, the timing rules, malformed
input, and fuzzing with random bytes and random JSON.

## Advanced HRV analysis (Kubios-compatible definitions)

`analysis/advanced.py` implements the analysis set of Kubios HRV (Tarvainen et al.,
*Comput. Methods Programs Biomed.* 2014) from published definitions. It runs on every
recording that yields at least 30 RR intervals: ECG files (after R-peak detection) and
RR files alike. It can be re-run from the session's **HRV analysis** tab
(`POST /api/v1/sessions/{id}/advanced`) with other options. Re-runs use the stored
beats (no ECG reprocessing) and are saved, so the screen, exports and PDF always agree.
NetriBeat isn't affiliated with Kubios; "Kubios-compatible" means "same definitions".

### Definitions checked against the user's Kubios report (D6, 21 Oct 2026)

| Item | Definition | Evidence in the report |
|---|---|---|
| log power | natural log | ln 317 = 5.759; ln 4291 = 8.364 |
| n.u. | band / (LF + HF) × 100 | 2192 / (4291 − 317) = 55.2 |
| pNN50 | NN50 / (n − 1) × 100 | 139 / 0.3777 = 368 differences |
| SD1 % / SD2 % (ANS panel) | SD1 / (SD1 + SD2) × 100 | 81.5 / 185 = 44.1 % |
| Stress index | √(Baevsky SI) | the report's 3.5 |
| Detrended vs not | Mean RR, Mean HR, Min/Max HR from non-detrended RR; the rest from detrended RR | the report footnote |

### Options and defaults

| Option | Default | Notes |
|---|---|---|
| Sample | first 300 s | Start and length are free; "to end" is allowed |
| Artefact correction | **low** | Kubios threshold levels at 60 bpm (very low 450, low 350, medium 250, strong 150, very strong 50 ms), scaled by the mean RR, compared with the 11-beat local median; flagged beats are replaced by cubic-spline interpolation. "none" and the NetriBeat §6 rule are also available. *Why low:* it flagged 0 beats in the clean D1 baseline (the §6 rule flags 20, i.e. normal breathing variation) yet catches the artefacts in D1 post-match. |
| Trend removal | smoothness priors, λ = 500 | Tarvainen et al. 2002, on the RR series by beat index |
| FFT | Welch, 4 Hz cubic-spline resampling, 256 s Hann windows, 50 % overlap, 300 points/Hz | |
| AR | Yule–Walker, order 16; band powers integrated on a 10 000 points/Hz grid | A coarse grid overstates narrow AR peaks (+27 % in a test with strongly periodic breathing) |
| Lomb–Scargle | the design-spec §6 method | shown for comparison |
| Bands | VLF 0–0.04, LF 0.04–0.15, HF 0.15–0.40 Hz | the Kubios band edges |
| Entropies | m = 2, r = 0.2 × SDNN | ApEn (Pincus 1991) and SampEn (Richman & Moorman 2000), verified against brute-force reference implementations in the tests |
| DFA | α1 over 4–16 beats, α2 over 16–64 beats | Peng et al. 1995; tested on white noise (α ≈ 0.5) and Brownian motion (α ≈ 1.5) |
| Recurrence plot | m = 10, τ = 1, r = √m × SDNN | REC, DET, Lmean, Lmax, ShanEn |
| Min/Max HR | 5-beat moving average | |
| Triangular index, TINN | 1/128 s (7.8125 ms) bins | Task Force 1996 |
| Time-varying | 60 s window, 10 s step | mean HR, RMSSD, SDNN, SD1, stress index |

ApEn, SampEn and the recurrence plot are O(N²); they're skipped, with a stated reason,
for samples longer than 4000 beats.

### Not implemented (and why)

- **PNS and SNS indexes.** These compare six values with Kubios' normative population
  values. The report confirms which values are used, but its numbers don't let me
  recover the normative means and SDs reliably, and guessing them would produce
  numbers that look official but aren't. The six component values *are* shown. If you
  have the normative table (Kubios user guide), it's a small addition.
- **Kubios "Automatic" artefact correction** (Lipponen & Tarvainen 2019): the threshold
  levels are implemented; the automatic method is not.
- **Correlation dimension D2, ECG-derived respiration (EDR), Readiness, energy
  expenditure, VO₂max and several samples in one report:** not implemented.
  Respiratory rate uses the HF peak (design-spec §6).

### What the supplied RR files show

- `D1BLHR.json`, `D1BLHR_RR.csv` and `{"rr": [...]}` give **identical** results. The
  ECG-derived `D1BLECG_RR_fromECG.csv` agrees with the sensor RR within 1 % (RMSSD
  68.1 vs 68.6 ms, SDNN 92.0 vs 92.1 ms).
- **The post-match recordings begin with heavy artefacts.** With the default (low)
  correction, the first 5 minutes of `D1PMHR_RR.csv` give SDNN ≈ 220 ms, which is not
  physiological. Use the trimmed files, move the sample (e.g. 10:00–15:00 gives RMSSD
  30.8 ms with medium correction), or choose a stronger correction level.
