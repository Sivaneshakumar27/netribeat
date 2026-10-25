# NetriBeat — task plan

Each task is a self-contained slice. A task is done only when it has working code,
tests, passing `make check` / `npm test`, and updated docs. Tasks are built in order.

| # | Task | Status |
|---|------|--------|
| 1 | Authentication: backend, pages, admin CLI | **Done** |
| 2 | Authentication dashboard (user security + admin users and audit) | **Done** |
| 3 | User profile and HRmax settings | **Done** |
| 4 | Session data model, ownership and isolation | **Done** |
| 5 | File storage, upload endpoint, background jobs | **Done** (local/volume storage; S3-compatible storage not yet) |
| 6 | Parsers for the supplied JSON and CSV formats | **Done** |
| 7 | ZIP import (preview → commit) with D-folder individuals | Not started: upload the files directly instead (multi-file upload works) |
| 8 | Analysis pipeline: R-peaks, RR, artefacts, quality | **Done**, with provisional P2–P5; detector limitation documented in docs/analysis.md |
| 9 | HR, zones, TRIMP, HRV time/frequency, Poincaré, respiration | **Done** (movement load: no input format carries accelerometer data) |
| 10 | Session list, session detail and charts | **Done** |
| 11 | PDF / CSV / JSON exports | **Done** |
| 13 | Advanced HRV (Kubios-compatible definitions), RR CSV/JSON input, Kubios-style PDF | **Done** — PNS/SNS indexes, automatic correction, D2, EDR and Readiness not yet (see docs/analysis.md) |
| 12 | Production deployment and hardening | Partly done: HTTPS stack, deployment guide, backups. Remaining: monitoring and alerting, worker service, object storage, admin 2FA |

## Task 1 — Authentication (done)

Registration with email OTP; email verification; resend with a cooldown and an hourly cap;
login in user and admin modes with identical failure responses; "keep me signed in";
short-lived access tokens plus a rotating HttpOnly refresh cookie with reuse detection;
logout; forgot password → OTP → single-use reset token → new password, which signs out
every device; change password; admin API to list/search/create/enable/disable users and
change roles; audit log; Redis rate limits; admin provisioning CLI; security headers;
body-size limit. The frontend has every authentication page and a signed-in account page.

## Task 2 — Authentication dashboard (done)

User: overview, name editing, signed-in devices with per-device and "all other devices" sign-out, password change. Admin: users table with search, filters, sorting, pagination, create, enable/disable, role change and sign-out-everywhere (all with confirmation dialogs and server errors shown inline), plus the audit log viewer. Backend: session listing and revocation endpoints with ownership checks.

## (original Task 2 plan)

- Admin dashboard shell: dark sidebar with Users and Audit log.
- Users table: search, role/status filters, sorting, pagination. Uses the existing
  `GET /api/v1/admin/users`.
- Create user (invite email), enable/disable, change role, with confirmation dialogs and
  last-admin / self-change errors shown.
- Audit-log viewer.
- Tests: component tests, plus an API test that a user can't reach any admin screen data.

## Task 3 — Profile and HRmax settings

- Edit name and age (the API exists); HRmax method `age | peak | manual` (100–230 bpm) per
  design-spec §6.
- `GET/PUT /api/v1/users/me/hrmax`. Recomputing stored zone results waits for Task 9.
- Account deletion with confirmation; a full cascade of recordings is added in Task 4/5.

## Task 4 — Sessions model and ownership

- `sessions`, `source_files`, `import_batches` and `analysis_results` tables, each with
  `user_id` ownership, foreign keys and indexes.
- Every read, write, export and delete is checked in the service layer. Another user's
  resource returns 404.
- Tests that swap UUIDs, filenames, export ids and request bodies across two users.

## Task 5 — Storage, upload, background jobs

- Storage interface: local disk for development, S3-compatible in production. Files are
  stored under opaque ids; original filenames are kept only as metadata.
- `POST /api/v1/sessions` (multipart, 50 MB per file) → status `processing`, an Arq job,
  HTTP 202. The job is idempotent, retries safely and survives a worker restart. Errors
  shown to users are safe; full diagnostics stay server-side.
- Worker process plus a Compose service.

## Task 6 — Parsers (evidence: docs/dataset-analysis.md)

- Parser registry and a normalised output (signal kind, units, time base, metadata,
  warnings).
- JSON ECG: 500 Hz, validated from timestamps. Gap detection that separates real packet
  loss from bunched timestamps.
- JSON RR: `rrData` in ms; sensor `average` kept as metadata.
- CSV ECG: 200 Hz, mV; metadata header parsed; gender and serial number discarded.
- HEX: explicit "unsupported format" response until `sensor-formats.md` is supplied.
- Golden tests using the supplied files.

## Task 7 — ZIP import

- Safe extraction: no path traversal, no symlinks; size, ratio and count limits.
- Preview: folders → individuals (D1, D2, D3, D4, D6; a future D5 needs no code change),
  files, detected signals, warnings. Then commit, with per-file success or failure.
- Every D-folder is its own individual, never merged. Every file is its own recording.
  An admin can link an individual to an account later.
- The JSON files have no age or recording date, so the admin enters them at import.

## Task 8 — Analysis core

Pan–Tompkins R-peaks with the exact constants in design-spec §6; RR intervals; the
11-beat-median 20 % artefact rule; quality `no_ecg` / `poor` / `good`. RR is never
computed across a gap. Synthetic and golden tests for every formula.

## Task 9 — Metrics

HRmax selection, zones and time-in-zone, Edwards TRIMP, RMSSD, SDNN, pNNI20/50,
Lomb–Scargle PSD (VLF/LF/HF, n.u., peaks), Poincaré SD1/SD2, respiration from the HF peak,
and movement load (no supplied file has accelerometer data). Missing inputs give explicit
"unavailable" reasons.

## Task 10 — Dashboards and charts

Session list, detail tabs (ECG and beats, HR, HRV, load and respiration), interactive
charts with crosshair and tooltips, processing / failed / retry states, and poor-quality
warnings. Stored results only; no calculations in the browser.

## Task 11 — Exports

PDF report, CSV and JSON exports generated from stored results only, with ownership
checks and provenance (analysis version, timestamps, warnings).

## Task 12 — Production

Dockerfiles; reverse proxy with HTTPS (Caddy or nginx); secrets handling; migrations on
deploy; backups and a restore drill; health checks and monitoring; log retention;
secret rotation and disabling compromised accounts; release checklist.

## Decisions still needed from the product owner

1. **The R-peak detector** fails on recordings with motion spikes (see docs/analysis.md). Should an adaptive threshold and a band-pass filter be added to §6?
2. **Confirm or change P2–P5** (currently applied provisionally).
3. **Confirm the implementation decisions** listed in docs/analysis.md.

## Background (original note)

None of the supplied recordings contains a 1 Hz heart-rate series, so zones and TRIMP
depend on proposals that `backend-stories.md` marks as unsettled:

- **P2:** split ECG into segments at recording gaps.
- **P3:** build 1 Hz HR by interpolating corrected beat HR.
- **P4:** treat RR intervals outside 250–2500 ms as artefacts. D1PMHR contains 7 values
  above 2500 ms.

Option A: adopt them provisionally, labelled "provisional" in results and reports.
Option B: wait for the product owner. Also needed: the unit of the JSON ECG samples
(undocumented raw integers) and `docs/sensor-formats.md` for HEX.
