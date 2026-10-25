# NetriBeat — Frontend Design Spec

Source of truth: `prototype/netribeat.html`. Everything below is taken from it. Where the prototype is incomplete, it is listed under **Gaps**.

---

## 1. Design tokens

### Colours

| Token | Light | Dark | Use |
|---|---|---|---|
| `--surface` | `#f5f4f0` | `#0c0c0d` | Page background |
| `--surface-raised` | `#ffffff` | `#151517` | Cards, panels |
| `--surface-sunken` | `#f8f7f4` | `#111113` | Inputs, tracks, table headers |
| `--line` | `#e8e5df` | `#26262a` | Borders, gridlines |
| `--line-strong` | `#76716b` | `#77777d` | Input borders, axes |
| `--ink` | `#141414` | `#f4f3f1` | Primary text |
| `--ink-muted` | `#5c5852` | `#b4b1ac` | Secondary text, labels |
| `--accent` | `#b4460a` | `#ff8a3d` | Links, accent text |
| `--accent-fill` | `#f26b1d` | `#ff7a2a` | Primary buttons, fills |
| `--on-accent` | `#111111` | `#111111` | Text on accent fill |
| `--chrome` | `#111112` | `#0a0a0b` | Sidebar background |
| `--chrome-line` | `#262628` | `#232326` | Sidebar borders |
| `--on-chrome` | `#f4f3f1` | `#f4f3f1` | Sidebar text |
| `--on-chrome-muted` | `#a9a6a1` | `#a9a6a1` | Sidebar secondary text |
| `--chrome-accent` | `#ff8a3d` | `#ff8a3d` | Sidebar accent |

**Data colours**

| Token | Light | Dark | Meaning |
|---|---|---|---|
| `--zone-1` | `#7b858f` | `#98a2ad` | Z1 Very light |
| `--zone-2` | `#3b6fb6` | `#6b9de0` | Z2 Light |
| `--zone-3` | `#2f8a68` | `#4fbf93` | Z3 Moderate |
| `--zone-4` | `#a97c00` | `#e3b43a` | Z4 Hard |
| `--zone-5` | `#c83d31` | `#f0685b` | Z5 Maximum |
| `--band-vlf` | `#8a857f` | `#77777d` | VLF band |
| `--band-lf` | `#a97c00` | `#e3b43a` | LF band (also SD2) |
| `--band-hf` | `#3b6fb6` | `#6b9de0` | HF band (also SD1) |
| `--status-good` | `#1f7a55` | `#5cc996` | Good / within reference |
| `--status-warn` | `#8a6300` | `#e3b43a` | Borderline |
| `--status-alert` | `#b3261e` | `#ff7a70` | Out of range / error |

Brand mark gradient: `linear-gradient(150deg, #ff8a3d, #e2560c)`.

### Typography

| Role | Font | Size / line-height | Weight |
|---|---|---|---|
| Body, UI | Geist | 14 / 21 | 400–500 |
| Page title | Sora | 28 / 34 | 700 |
| Session title | Sora | 26 / 32 | 700 |
| Panel title | Sora | 14.5 / 20 | 600 |
| KPI value | Sora | 26 / 32 | 700 |
| Big HR numbers | Sora | 36 / 40 | 600 |
| Tile label | Geist, UPPERCASE, letter-spacing .06em | 11 / 16 | 600 |
| Chart text | Geist | 11.5 | 500 |

All numbers use tabular figures (`font-variant-numeric: tabular-nums`).

### Spacing, radius, shadow

| Token | Value |
|---|---|
| Spacing | 4, 8, 12, 16, 24, 32 px |
| Radius sm / md / lg | 6 / 10 / 16 px |
| `--shadow-card` | Light `0 14px 34px -24px rgba(40,30,20,.35)` · Dark `0 18px 40px -22px rgba(0,0,0,.7)` |
| `--shadow-float` | Light `0 12px 32px rgba(20,20,20,.12)` · Dark `0 12px 32px rgba(0,0,0,.5)` |

### Theme

Light and dark, toggled from the sidebar footer. Set via `data-theme` on `<html>`; choice stored in `localStorage` key `netribeat-theme`.

---

## 2. Layout

- **Shell:** fixed black sidebar (248 px) + main area (padding 30/34 px, content max-width 1320 px).
- **Grid:** 12 columns, 16 px gap. KPI rows use 4 or 5 equal columns.
- **Breakpoints:**

| Width | Change |
|---|---|
| ≤ 1300 px | Training-load mini-bars hidden in tables |
| ≤ 1100 px | 5-column KPI rows → 3 columns |
| ≤ 960 px | Upload page → single column |
| ≤ 900 px | Sidebar becomes a top bar; KPI rows → 2 columns |
| ≤ 720 px | All grid panels full width |

**Sidebar:** brand (logo + "NetriBeat") · **New recording** button · nav (Dashboard, Sessions, Session view — disabled until a session is opened, Settings) · footer (user email, theme toggle, Sign out).

---

## 3. Screens

### 3.1 Login
- Left: dark brand panel — wordmark, one-line description, 3 numbered steps, ECG wave graphic.
- Right card: **Email** (required), **Password** (required), "Keep me signed in" (checked), "Forgot password?", **Sign in**.
- Email is trimmed and lower-cased. Errors appear after the first submit: *"Enter a valid email address, like name@institute.org"*, *"Enter your password"*.

### 3.2 Dashboard
- Heading: "Good to see you, {email name}".
- 4 KPI tiles (latest session): Avg HR (sub: max HR · type), RMSSD (sub: ±z SD vs mean of all sessions), Training load (AU), Signal quality (badge + % beats corrected).
- 2 trend panels (sessions sorted by date, needs ≥ 2):
  - **RMSSD by session** — line; shaded band = mean ± 0.5 SD; dashed line = mean.
  - **Training load by session** — bars coloured by session type; dashed line = mean.
- **Recent sessions** — first 6 rows of the sessions table + "All sessions →".

### 3.3 New recording (upload)
Header with 3-step progress: Athlete → Session → Files.

| Card | Fields | Rules |
|---|---|---|
| 1 Athlete | Athlete email *, Age *, Max HR override (optional) | Email valid; suggestions from existing athletes. Age 8–100. Override 100–230 bpm, empty = 210 − age. Shows "Zones will use X bpm" + source. |
| 2 Session | Session type (chips), Recorded on (date-time), Device (select), Notes (optional) | Type default *Training*; device default *Chest strap (RR + ACC)* |
| 3 Files | Drop zone, Choose files, Use sample data | Accepts `.csv .txt .fit .hrm .edf`, ≤ 50 MB each. File type guessed from name: contains `acc`/`imu`/`motion` → ACC; `hr`/`heart` → HR; else RR. Each file can be removed. |

Sticky bottom bar: "Tracked to {athlete} · {type} · N files", **Cancel**, **Upload and analyse →**.
Validation messages appear after the first submit (max-HR error shows immediately).

### 3.4 Sessions
- Header + **+ New session**.
- 4 stats for the current filter: Sessions, Athletes, Recorded time, Avg RMSSD.
- Toolbar: search (email, file, type) + athlete filter.
- Table columns: **Session** (type pill + date) · Athlete · Duration · Avg HR · Max HR · RMSSD ("N/A" when no ECG) · Training load (mini-bar + value) · Quality · View / Report.
- Whole row is clickable (and Enter-key accessible) → Session view.

### 3.5 Session view
**Header:** "← Sessions" · date · duration · "{Type} session" · athlete · age · device · file name · quality badge · **Export report**.
**Banner** (if any artefacts): "N beats (X %) were corrected as artefacts — all HRV results use the corrected series."
**Tabs:**

| Tab | Content |
|---|---|
| **Overview** | 10 KPI tiles: Avg HR, Max HR (% of HRmax), Min HR, RMSSD, pNNI50, LF/HF (with LF/HF n.u.), SD1 (with SD2), Respiratory rate, Training load, Movement load. HR-over-time chart (8 cols) + zone distribution (4 cols). |
| **ECG & beats** | 4 stats: Beats detected, Artefacts corrected (alert tag if > 5 %), Mean beat HR, Beat HR range. ECG strip (first 10 s) with R-peak markers and RR (ms) labels. Beat-to-beat chart with HR (bpm) / RR (ms) toggle; artefacts shown as red ring at raw value linked to the corrected line. |
| **Heart rate** | HR summary: Min, Avg, Max (each with % of HRmax), HRmax used (with its source) + range bar over zones, and a **"Change max HR in Settings"** link. HR-over-time chart. Zone distribution. Max HR is not edited here — it comes from the athlete's setting (3.6). |
| **HRV** | **Time domain:** RMSSD, pNNI20, pNNI50 (reference tags: RMSSD 19–75 ms, pNNI50 3–45 %), plus mean RR, SDNN, mean HR, beats. **Frequency domain:** PSD chart with VLF/LF/HF shading and LF/HF peaks; band table (range, peak, power ms², %, n.u.); LF/HF ↔ HF/LF toggle; total power. **Poincaré:** scatter RRₙ vs RRₙ₊₁, identity line, SD1/SD2 ellipse; SD1, SD2, SD1/SD2, beats. |
| **Load & respiration** | Training load meter, Movement load meter + per-minute sparkline, Respiratory rate (normal band 12–20) + per-minute sparkline. |

**Chart behaviour:** SVG, responsive to container width. HR and beat charts show a crosshair + tooltip on hover. HR-over-time line is coloured by zone; HRV window (0–5 min) is shaded.

### 3.6 Settings
Page title "Analysis settings". Max HR is set **per athlete** and drives HR zones, the zone split and training load for all of that athlete's sessions.

| Panel | Content |
|---|---|
| **Max HR** (7 cols) | **Athlete** select (hint: N sessions · age). Three radio rows, each showing its bpm value: **Age-based** (210 − age) · **Session peaks** (highest session peak) · **Manual** (entered by user; shows a bpm input, 100–230). **Save max HR** button — enabled only when changed and valid. Status text: "Unsaved changes" / "Saved · X bpm for {email}" / "Using X bpm · {source}". |
| **Zones at X bpm** (5 cols) | Live table for the selected value: Zone (Z5 → Z1) · % HRmax · bpm range. |

---

## 4. Components

| Group | Components |
|---|---|
| Primitives | `Button`, `SegmentedControl`, `Field`, `StatusTag`, `QualityBadge`, `TypePill`, `AthleteTag`, `Icon`, `Sparkline` |
| Containers | `AppShell`, `Panel`, `MetricTile`, `Stepper`, `ChoiceGroup`, `DropZone` |
| Charts | `HRZoneChart`, `SignalStrip`, `BeatHRChart`, `PSDChart`, `PoincarePlot`, `SessionTrend` |
| Data blocks | `HRSummary`, `ZoneSplit`, `HRMaxControl` (Settings, stacked radio variant), `BeatDetection`, `TimeDomain`, `BandPowerTable`, `LoadMeter`, `RespiratoryRate` |
| Pages | `LoginPage`, `HomeDashboard`, `UploadForm`, `SessionList`, `AnalysisDashboard`, `SettingsPage`, `AppFlow` (router) |

**Badges**
- Quality: **Good** (green, dot) · **Poor** (red, triangle) · **No ECG** (grey, ring). Shape differs, not just colour.
- Session type colour: Training = accent orange · Rest / baseline = zone-2 blue · Match / competition = zone-5 red · Recovery = zone-3 green · Test protocol = zone-4 amber.

---

## 5. Enumerations (UI label → API value)

| Session type | API |
|---|---|
| Rest / baseline | `rest` |
| Training | `training` |
| Match / competition | `match` |
| Recovery | `recovery` |
| Test protocol | `test` |

| Device | API |
|---|---|
| Chest strap (RR + ACC) | `chest_strap_rr_acc` |
| Chest strap (RR only) | `chest_strap_rr` |
| ECG Holter | `ecg_holter` |
| Optical wrist sensor | `optical_wrist` |
| Other | `other` |

| File kind | API |
|---|---|
| RR intervals | `rr` |
| Raw ECG | `ecg` |
| Heart rate (1 Hz) | `hr` |
| Accelerometer | `acc` |

Quality: `good` · `poor` · `no_ecg`. Max HR method: `age` · `peak` · `manual`.

---

## 6. Metric definitions (shared with backend)

| Metric | Definition |
|---|---|
| Max HR (HRmax) | Methods — `age`: 210 − age (default). `peak`: highest max HR across the athlete's sessions. `manual`: user value, 100–230 bpm. **Which one applies:** athlete's saved setting (Settings) → else the session's upload override → else age-based. |
| HR zones (% HRmax) | Below Z1 < 50 · Z1 50–60 Very light · Z2 60–70 Light · Z3 70–80 Moderate · Z4 80–90 Hard · Z5 ≥ 90 Maximum |
| Time in zone | From 1 Hz HR samples |
| Training load | Edwards TRIMP = Σ (minutes in zone × zone number 1–5), AU |
| Movement load | Σ √(Δx² + Δy² + Δz²) / 100 over tri-axial ACC (g), AU |
| R-peak detection | Pan–Tompkins style: derivative → square → 150 ms moving integration → threshold 0.3 × max → 250 ms refractory → refine to raw-signal maximum |
| RR / beat HR | RR = interval between R peaks (ms). Beat HR = 60 000 / RR |
| Artefact correction | Beat > 20 % from median of local 11-beat window → flagged and replaced by that median |
| HRV window | First 5 min (0–300 s) of the corrected RR series |
| RMSSD | √mean(ΔRR²), ms |
| pNNI20 / pNNI50 | % of \|ΔRR\| > 20 / 50 ms |
| SDNN | Sample SD of RR, ms |
| PSD | Lomb–Scargle, 0.002–0.5 Hz in 0.002 Hz steps, scaled so total power = RR variance |
| Bands | VLF 0.0033–0.04 · LF 0.04–0.15 · HF 0.15–0.4 Hz. % = band / (VLF+LF+HF). n.u. = LF or HF / (LF+HF) × 100 |
| Poincaré | SD1 = SD(ΔRR) / √2. SD2 = √(2·SDNN² − SD1²) |
| Respiratory rate | HF peak (Hz) × 60, breaths/min |
| Signal quality | `no_ecg` if < 30 RR intervals · `poor` if artefacts > 5 % · else `good` |

**Display scales**

| Meter | Bands |
|---|---|
| Training load (AU) | Low < 50 · Moderate < 120 · High < 200 · Very high (scale to 300) |
| Movement load (AU) | Low < 100 · Moderate < 250 · High < 400 · Very high (scale to 550) |
| Respiratory rate | Track 6–36 br/min, normal 12–20 |

---

## 7. Gaps in the prototype (to build)

| Item | Current state |
|---|---|
| Authentication | Any email + password signs in; "Keep me signed in" does nothing |
| Forgot password | Link has no action |
| Export report / Report link | Button does nothing; Report link opens the session |
| File handling | Files are not read; analysis runs on generated demo data |
| Persistence | Everything is in memory; refresh resets |
| Upload rule | Accepts any file; should require at least one RR or ECG file |
| Max HR settings | Saved in memory only; lost on refresh. Session list values (training load) don't yet use the saved setting. |
| Loading / error states | None (prototype computes instantly) — needed for upload processing and API errors |
