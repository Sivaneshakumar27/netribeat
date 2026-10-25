# NetriBeat — Backend Stories

Stack and rules: `CLAUDE.md`. Contract: `docs/api-spec.yaml`. Formulas: `docs/design-spec.md` §6. Sensor file format: `docs/sensor-formats.md`.

## Processing flow

```
ECG sensor ─► hex file ─► ECG signal extraction ─► R-peaks ─► RR intervals ─► derived metrics
```

| Stage | Story | Defined in |
|---|---|---|
| Read the hex file, extract the ECG signal | SES-4 | `sensor-formats.md`, P1, P2 |
| Detect R-peaks; RR intervals; artefacts; quality | SES-6 | §6 R-peak detection, RR, Artefact correction, Signal quality |
| HR, zones, training load | SES-7 | §6 Max HR, HR zones, Time in zone, Training load |
| HRV and respiratory rate | SES-8 | §6 HRV window to Respiratory rate |
| Movement load | SES-9 | §6 Movement load, P6 |
| Assemble, store, recompute | SES-10 | — |

Uploads of RR, ECG, HR and ACC files (design-spec §3.3) feed the same stages through SES-5.

## Ownership

| Track | Owner | Epics |
|---|---|---|
| A | Developer 1 | Foundation (BE-0), Auth (AUTH), Users (USR); in weeks 7–9 also SES-5, SES-12, SES-15 |
| B | Developer 2 | Sessions (SES): sensor format, hex decoding, upload, processing, analysis, read APIs, validation |

Sizes: **S** ≈ 1 day · **M** ≈ 2–3 days · **L** ≈ 4–5 days. Track A is about 21 working days for its own epics, plus about 7 for SES-5, SES-12 and SES-15; Track B is about 38 (see *Suggested order*).

## Users and roles

- **One kind of account: a user.** Identified by `id` (UUID); `email` is unique and used to sign in. Has age and a max-HR setting. A password is optional until the user sets one.
- **Roles:** `user` or `admin`.
- **How users are created:** by an admin with `netribeat create-user`, or automatically when an admin uploads a session for an email that doesn't exist yet. An upload-created user has role `user` and no password; they get a login through "forgot password". There is no sign-up screen.
- **Uploading:** a `user` uploads only for their own email; an `admin` uploads for any email.
- **Visibility:** a `user` sees only sessions tracked to them and only their own profile. An `admin` sees all users and sessions. Only admins can delete.
- **Ids, not emails, in URLs:** user endpoints are `/users/{id}`; the sessions filter is `userId`. Emails stay out of paths, so they stay out of access logs.
- **Why these rules:** anyone whose email is used in an upload can later get a login, so a normal user must never see or change other people's data.

## How the two tracks connect

Agree these on day 1. Until the real one lands, each side codes against a stub with the same signature.

| Interface | Owner | Used by | Signature (Python) |
|---|---|---|---|
| Current user | A | B | `auth.deps.current_user() -> User` (FastAPI dependency) |
| Admin only | A | B | `auth.deps.require_admin() -> User` |
| Upsert user on upload | A | B | `users.service.upsert_user(db, email: str, age: int) -> User` |
| HRmax resolution | A | B | `users.hr_max.resolve(user, session_age: int, session_override: int \| None, peak_max_hr: float \| None) -> HrMax(value, method, label, detail)` (pure) |
| Peak max HR for a user | B | A, B | `sessions.service.peak_max_hr(db, user_id) -> float \| None` |
| Stats for the user list | B | A | `sessions.service.user_session_stats(db, user_ids) -> dict[UUID, SessionStats]`, where `SessionStats(count: int, last_recorded_at: datetime \| None, peak_max_hr: float \| None)` |
| Recompute zone metrics | B | A | `sessions.service.recompute_zone_metrics(db, user_id) -> int` (sessions updated; resolves max HR per session, since each session has its own age) |
| Delete a user's sessions | B | A | `sessions.service.delete_sessions_for_user(db, user_id) -> int` (sessions tracked to the user, with their results and files) |

## Points the design spec doesn't define yet

Design-spec §6 defines every metric. These inputs and edge cases aren't covered yet. The product owner settles each one and records it in §6 or `docs/sensor-formats.md`; a story marked *blocked by* waits for it. `CLAUDE.md` forbids inventing them. **P1 and P2 are needed in week 1; P3–P6 by week 5.**

| # | Point | Proposal | Blocks |
|---|---|---|---|
| P1 | ECG sensor hex file format | `docs/sensor-formats.md` describes the file: header contents, packet layout, ECG sampling rate and units, timestamps, and how gaps, restarts and the start and end of a recording are marked. v1 assumes one recording per file. | SES-0, SES-4 |
| P2 | Gaps in the ECG | Split the signal into segments at every gap; detect R-peaks per segment; never compute an RR interval across a gap. A recording with more than 10 % of its samples missing fails with a clear message. | SES-4, SES-6 |
| P3 | 1 Hz HR when there's no HR file | Linear interpolation of corrected beat HR onto a 1 s grid. | SES-7 |
| P4 | RR outside 250–2500 ms | Flagged as artefacts and replaced like other artefacts. | SES-6 |
| P5 | Per-minute series on the *Load & respiration* tab | Movement load summed per minute; respiratory rate from the HF peak of a 2-minute window, stepped each minute. | SES-8, SES-9 |
| P6 | Movement data in the hex file | §6 computes movement load from tri-axial x/y/z acceleration. If the hex file carries movement in another form, §6 needs a formula for it; until then hex-only uploads report `movementLoad: null`. | SES-9 |

---

## Epic BE-0 — Foundation (Track A, first)

### BE-0.1 Backend scaffold · M
Set up the backend so both developers can start.

**Acceptance criteria**
- `backend/` with the layout in `CLAUDE.md`; `uv sync` installs; `make check` runs ruff, mypy and pytest.
- `docker-compose.yml` with Postgres and Redis; Alembic configured with an empty first revision.
- `config.py` reads all settings from env vars (`DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `STORAGE_DIR`, …); `.env.example` with dummy values; `.env` in `.gitignore`.
- A `netribeat` command-line entry point (`cli.py`) that AUTH-1 adds commands to.
- `ApiModel` base (camelCase aliases); `errors.py` with `AppError` subclasses including `Forbidden`; a global handler returns the `Error` schema. Request validation errors return **400** `validation_error` with `fields`.
- `GET /api/v1/health` returns 200 (excluded from the contract test).
- CI runs `make check` on every pull request.
- `tests/conftest.py` with `client` and rolled-back `db` fixtures; `tests/factories.py` started; `tests/contract/` skeleton that loads `docs/api-spec.yaml`.

**Tests:** error handler maps each `AppError` to the right status and body; validation error returns 400 with `fields`; health returns 200.

### BE-0.2 API spec updates · S
Update the contract before either track builds on it.

**Acceptance criteria**
- The current spec, design spec and prototype call people "athletes". Rename to users throughout `docs/api-spec.yaml` and `docs/design-spec.md`:
  - the tag and paths become `Users`, `GET /users` and `PUT /users/{id}/hr-max`
  - the profile schema becomes `UserProfile` and gains `id`
  - the sessions-list stat becomes `stats.users`
  - UI labels become "User email" and similar
- `User` (the signed-in account) gains `name` and `role` (`user` | `admin`).
- New `POST /auth/reset-password` (AUTH-5).
- New `DELETE /users/{id}` (USR-5) and `DELETE /sessions/{id}` (SES-13): admin only, 204.
- No emails in paths: the `GET /sessions` filter `email` becomes `userId`.
- `POST /sessions`: `email` is optional for a `user` (defaults to their own) and required for an admin; a `user` sending another email gets 403. New 413 limits: 10 files, 200 MB in total.
- New shared responses: 403 `forbidden`; 429 `too_many_attempts` on login and forgot-password.
- `GET /users` gains an optional `q` query parameter (email prefix, for upload-form suggestions).
- `SessionSummary` gains `userId` and `uploadedBy` (the uploader's id, null if that user was deleted); `Session` gains `progress` (nullable string).
- `GET /sessions/{id}` documents `Retry-After` while `processing`.
- Session id examples become UUIDs.
- The visibility rule (see *Users and roles*) is written into the spec description.
- The frontend team is told about the renames.
- Upload accepts the ECG sensor's hex file: `.hex` added to the allowed extensions in `api-spec.yaml` and design-spec §3.3; a `.hex` file is kind `ecg`; the device list (§5) gains "ECG sensor" (`ecg_sensor`), the default when a hex file is uploaded.
- Points P1–P6, once settled, are written into design-spec §6 and `docs/sensor-formats.md` by the product owner (not this story).

---

## Epic AUTH — Authentication (Track A)

### AUTH-1 User accounts, roles and the create-user command · M
**As an** admin, **I want** to create accounts **so that** the right people can sign in.

**Acceptance criteria**
- `users` table: `id` (UUID), `email` (unique, normalised), `name` (nullable), `role` (`user` | `admin`), `password_hash` (nullable: upload-created users have no login yet), `age` (nullable until set), `hr_max_method`, `hr_max_manual`, `is_active`, `token_version`, `created_at`, `updated_at`.
- Passwords hashed with argon2; never stored or logged in plain text. Minimum 8 characters.
- `netribeat create-user --email … --name … --role user|admin` prompts for a password. If the email already exists without a password, it sets one (and the role). If the email already has a password, it fails with "User already has a login; use forgot password or set-role".
- `netribeat set-role --email … --role user|admin` changes the role and increments `token_version`.
- `netribeat disable-user --email …` sets `is_active = false` and increments `token_version`.
- Shared email normaliser (`strip().lower()`) used everywhere.

**Tests:** hash/verify round trip; wrong password fails; emails with spaces/capitals stored normalised; duplicate email rejected; short password rejected; create-user on an upload-created user sets the password; create-user on a user with a password fails; set-role and disable-user invalidate existing tokens (with AUTH-3); disabled user can't sign in (with AUTH-2).

### AUTH-2 Sign in — `POST /auth/login` · M
**As a** user, **I want** to sign in with email and password **so that** I can see my sessions.

**Acceptance criteria**
- Valid credentials for an active user → 200 `LoginResponse` with a JWT `token`, `expiresAt` and `user`.
- `remember: true` → token valid 30 days; `false` → 12 hours (values in config).
- Token claims: user id, `token_version`, expiry. No role: the role is read from the database on each request (AUTH-3).
- Unknown email, wrong password, user with no password yet and disabled user all return the same 401 `invalid_credentials` body, so it doesn't reveal which emails exist.
- Missing or invalid fields → 400 with `fields` matching the UI ("Enter a valid email address, like name@institute.org", "Enter your password").
- Rate limits, counters in Redis: 10 failed attempts per email in 15 min, or 30 per IP address in 15 min → 429 `too_many_attempts`.
- Signing out is client-side (the app forgets the token).

**Tests:** happy path; both expiries; each 401 case gives an identical body; 400 messages; per-email and per-IP limits trip and reset (frozen time).

### AUTH-3 Auth dependencies and `GET /auth/me` · S
**As a** returning user, **I want** my sign-in restored on page load.

**Acceptance criteria**
- `current_user` reads `Authorization: Bearer …`, checks signature and expiry, loads the user, and checks `is_active` and `token_version`. `role` comes from the loaded user, never from the token.
- Missing, malformed, expired, tampered or outdated token → 401 `unauthorized`.
- `require_admin` → 403 `forbidden` for role `user`.
- `GET /auth/me` returns the `User`, including `role`.
- Every route except login, forgot-password, reset-password and health uses `current_user`, enforced by a test that walks the route table.

**Tests:** each 401 case; 403 for a `user` on an admin route; after `set-role` or `disable-user`, the old token gets 401; a role changed in the database takes effect on the very next request, without a new token; `/auth/me` happy path; route-table test fails if a new route forgets auth.

### AUTH-4 Forgot password — `POST /auth/forgot-password` · M
**Acceptance criteria**
- Always 204, whether or not the email exists.
- For an active user, including an upload-created user with no password yet (this is how they get a login): create a single-use reset token (random, stored hashed, expires in 1 hour) and email a link containing it. Requesting again invalidates the previous token.
- Rate limits, counters in Redis: at most 3 emails per address per hour (requests over that still return 204 but send nothing, so the limit reveals nothing); 10 requests per IP address per hour → 429 `too_many_attempts`.
- Email goes through an `EmailSender` interface: console sender in dev and tests, real provider via config (open question 2).

**Tests:** 204 for a known and an unknown email; token stored hashed; the fake sender gets exactly one email for a known user and none otherwise; works for a user with no password; the 4th request in an hour sends nothing; per-IP limit returns 429.

### AUTH-5 Reset password — `POST /auth/reset-password` · S
Body `{token, password}`.

**Acceptance criteria**
- Valid, unexpired, unused token → sets the new password, marks the token used, increments `token_version` (signs out other devices), 204.
- Invalid, expired or used token → 400 `invalid_reset_token`.
- Password under 8 characters → 400 with `fields.password`.

**Tests:** happy path then sign in with the new password; an upload-created user can sign in after reset and sees only their own sessions; an old token is rejected after reset; reuse fails; expired fails (frozen time); short password fails.

---

## Epic USR — Users and max HR (Track A)

### USR-1 Upsert user on upload · S
Provides `users.service.upsert_user(db, email, age)` for SES-2. Only ever called for the uploader's own email or by an admin (SES-2 enforces this), so nobody can change another person's age.

**Acceptance criteria**
- Unknown email → creates a user with role `user`, no password, the given age and no max-HR setting.
- Known email → updates `age` to the latest upload's; never changes role, password or name.
- Email normalised.

**Tests:** create; update age; normalisation; an existing admin stays admin; two concurrent upserts of the same email create one row.

### USR-2 Max HR resolution · S
Provides `users.hr_max.resolve(...)` for the sessions pipeline and the user list. Pure function.

**Acceptance criteria**
- Order: user's saved setting → session's `hrMaxManual` → `210 − age` (design-spec §6).
- *Age* is the session's age at recording (`session_age`), not the user's current age, so old sessions keep the zones they were recorded with.
- Saved `peak` uses `peak_max_hr`: the highest `maxHr` across the user's `ready` sessions, rounded to the nearest bpm; with none yet, falls back to age-based.
- Returns `value`, `method`, `label` ("Age-based", "Session peaks", "Manual") and `detail` (e.g. "210 − age (age 29)"), matching `Analysis.hrMax`.

**Tests:** each branch of the order; the session's age is used, not the user's; peak with no sessions; labels and detail strings; age 8 and 100; manual 100 and 230.

### USR-3 List users — `GET /users` · M
Feeds the upload form's email suggestions, the sessions filter and the Settings page.

**Acceptance criteria**
- Returns `UserProfile[]`: `id`, `email`, `sessionCount`, `lastRecordedAt`, `age`, `peakMaxHr`, `hrMaxSetting` (null when none saved), `hrMaxValue` (age-based uses the user's current age here, as a preview).
- `admin` gets every user with at least one session or a login; `user` gets only their own profile.
- Sorted by `lastRecordedAt` desc, then email. Optional `q` filters by email prefix (for the admin upload form's suggestions).
- Counts, last recorded date and peak max HR come from one `user_session_stats` call (no N+1 queries).

**Tests:** fields for a user with and without sessions and with each max-HR method; admin sees all, user sees only self; `q` filter; query count ≤ 3; 401 without a token; response matches the schema.

### USR-4 Save max HR — `PUT /users/{id}/hr-max` · M
**As a** user, **I want** to set my max HR **so that** zones and training load are right for all my sessions. Admins can set it for anyone.

**Acceptance criteria**
- Body `HrMaxSetting`. `method: manual` needs `manual` 100–230, else 400 with `fields.manual`; `manual` is ignored for other methods.
- A `user` can change only their own; another id → 404. Unknown id → 404.
- Saves the setting, then calls `recompute_zone_metrics(user_id)` in the same request; returns the updated `UserProfile`.
- Afterwards every `ready` session for that user returns the new `hrMax`, zones and training load, and the sessions list shows the new training load.

**Tests:** each method; validation errors; user on own id works; user on another id gets 404; admin on any id works; after saving, `GET /sessions/{id}/analysis` reflects the new value (API test with `run_jobs_inline`).

### USR-5 Delete a user and all their data — `DELETE /users/{id}` · S
**As an** admin, **I want** to remove a user completely **so that** we can honour a request to delete their data.

**Acceptance criteria**
- Admin only (403 for `user`); unknown id → 404; deleting your own account → 400 `cannot_delete_self`.
- Calls `delete_sessions_for_user` (sessions tracked to the user, with results and stored files), then deletes the user. 204.
- Sessions this user uploaded for other people are kept; their `uploaded_by` becomes null.
- Logs the deleted `user_id` and the admin's id, not emails.

**Tests:** happy path removes user, sessions and files; sessions they uploaded for others remain with `uploadedBy: null`; `user` gets 403; 404; self-delete refused; the user no longer appears in `GET /users` or `GET /sessions`.

---

## Epic SES — Sessions (Track B unless noted)

### SES-0 Sensor file format spec and test files · M · *blocked by P1*
**As a** developer, **I want** the hex file format written down and a way to make test files **so that** decoding is built and tested against a spec, never against real people's recordings.

**Acceptance criteria**
- `docs/sensor-formats.md`, agreed with whoever owns the sensor firmware: header fields (marking which are personal data), packet layout byte by byte, ECG sampling rate and units, timestamps, how gaps, restarts and recording start/end are marked, and movement data if present.
- `factories.hex_file(...)` writes valid synthetic hex files from a given ECG signal, with options for gaps, duplicate and out-of-order packets, restarts and a corrupted packet.
- Two or three synthetic hex files are committed under `tests/fixtures/hex/`.

**Tests:** factory files match the spec's layout (field positions checked byte by byte); the same inputs produce identical files (deterministic).

### SES-1 Session and file models, storage · M
**Acceptance criteria**
- Tables:
  - `sessions`: `id` UUID, `user_id` (FK → users), `uploaded_by` (FK → users, nullable, `ON DELETE SET NULL`), `type`, `recorded_at`, `device`, `notes`, `age`, `hr_max_manual`, `status`, `progress`, `error`, `duration_s`, summary metrics, `created_at`
  - `session_files`: `name`, `kind`, `size_bytes`, `storage_key`
  - stored analysis + signals (JSONB in v1)
- `storage.py` interface: `save(stream) -> key`, `open(key)`, `delete(key)`; local-disk implementation under `STORAGE_DIR`.
- Indexes for list queries (`user_id`, `recorded_at desc`).
- One service helper applies the visibility rule (admin: everything; user: `user_id` is theirs). Every session query uses it.

**Tests:** storage round trip on `tmp_path`; delete removes the file; model constraints (enums, required fields); visibility helper for admin, owner and stranger.

### SES-2 Upload — `POST /sessions` · L
**As a** user, **I want** to upload my recording files **so that** they're analysed and kept on my record. Admins can upload for anyone.

**Acceptance criteria**
- Who for: a `user`'s session is tracked to their own email (`email` may be omitted; any other email → 403 `forbidden`). An admin must give `email`.
- Multipart fields per spec; 400 with `fields` for: invalid email, age outside 8–100, `hrMaxManual` outside 100–230, unknown `type`/`device`, notes over 500 characters, no files.
- File kind: a `.hex` file → `ecg` (from the ECG sensor); otherwise from the name: `acc`/`imu`/`motion` → `acc`; `hr`/`heart` → `hr`; `ecg` → `ecg`; else `rr`. Allowed extensions `.hex .csv .txt .fit .hrm .edf`.
- At least one `rr` or `ecg` file, else 400 `fields.files` "Add at least one RR or ECG file".
- Any file over 50 MB, more than 10 files, or more than 200 MB in total → 413 (checked while streaming, not after loading into memory; limits in config).
- Calls `upsert_user(email, age)`, stores files, creates the session with `status: processing` and `uploadedBy` = current user, enqueues `analyse_session(id)`, returns **202** `Session`.

**Tests:** happy path returns 202 and the job is enqueued; a `user` uploading for another email gets 403 and nothing is stored; an admin uploading for a new email creates a `user` with no password; every 400 case; each 413 limit; kind inference including `.hex` (parametrised); 401 without a token.

### SES-3 Job runner, status and polling · M
**Acceptance criteria**
- Arq worker runs `analyse_session(id)`; 5 min timeout; no retry for bad input, 2 retries for infrastructure errors.
- Status `processing` → `ready`, or → `failed` with a user-readable `error` ("No usable RR or ECG data found", "File could not be read: …"). Stack traces are logged, never returned.
- `progress` updated per stage: "Reading files", "Extracting ECG", "Detecting beats", "Computing heart rate", "Computing HRV", "Saving results".
- `GET /sessions/{id}` returns the session if visible (else 404); while `processing` it sends `Retry-After: 2`.
- Re-running a job overwrites its results (idempotent).
- A periodic sweep marks a session `failed` when it has been `processing` longer than `timeout × (retries + 1)` plus a queue allowance: 20 min with the defaults, computed from config so it can't fall below the retry window.
- Until SES-10 lands, the job runs a **stub pipeline** that waits briefly and saves a fixture `Analysis` + `Signals`. This lets the frontend build upload, polling and the session view against real endpoints from week 4.

**Tests:** success and failure paths with `run_jobs_inline`; `Retry-After` only while processing; 404 for a session the user can't see; idempotent re-run; the sweep leaves a session alone at 19 min and fails it at 21 (frozen time); the sweep threshold is never below the retry window.

### SES-4 ECG sensor hex file: decode and extract the ECG · L · *blocked by P1, P2*
**As a** user, **I want** the hex file from my ECG sensor read correctly **so that** every beat in my recording is analysed.

Pure functions in `parsers/hex.py`, per `docs/sensor-formats.md`.

**Acceptance criteria**
- Reads the header and keeps only what the analysis needs (per `sensor-formats.md`); any other header fields are discarded, never stored or logged.
- Decodes the packets into ECG samples with their timestamps, in order. Duplicate and out-of-order packets are handled as the format spec says.
- Builds the ECG signal on a fixed time grid at the sensor's sampling rate, with a mask for missing samples, and splits it into segments at gaps (P2).
- Returns segments (`signal`, `fs`, `start_time`, missing-sample mask), the recording's start and end time, and counts of packets decoded, duplicated, out of order and missing.
- Movement data, if the file carries it, is returned separately for SES-9 (P6).
- An unreadable or empty file raises `ParserError` with a plain message; SES-3 turns it into `failed`.

**Tests:** round trip with `factories.hex_file()` (decode what the factory encoded); known-answer tests for the packet layout; a gap creates two segments, exactly at and just over the threshold; duplicate, out-of-order and missing packets; header fields outside the allowed list never appear in the result; empty file and header-only file → readable errors; property: every sample's timestamp lies inside its segment.

### SES-5 Other input files (CSV/TXT) · M · *Track A, weeks 7–8*
**Acceptance criteria**
- `parsers/` reads RR (ms per line or column), raw ECG (sampling rate from the file header), HR at 1 Hz and tri-axial ACC (x/y/z in g). Header detection; comma, semicolon or tab; blank lines and comments tolerated.
- Same output types as SES-4 (ECG segments, RR array, HR series, ACC series), so the analysis doesn't care where the data came from.
- Out-of-range values are kept and flagged per P4, not dropped. Unreadable files raise `ParserError` with a line number where possible.

**Tests:** one synthetic fixture per kind and delimiter; malformed lines; empty file; units.

### SES-6 Beat detection, artefacts and quality · L · *blocked by P2, P4*
Pure functions in `analysis/`, per design-spec §6.

**Acceptance criteria**
- R-peak detection per §6 (derivative → square → 150 ms moving integration → threshold 0.3 × max → 250 ms refractory → refine to the raw-signal maximum), run over each whole segment, skipping masked samples.
- RR (ms) between consecutive beats in the same segment only; never across a gap (P2). Beat HR = 60 000 / RR. With only an RR file, skip detection.
- Artefacts: beat more than 20 % from the median of its local 11-beat window → flagged and replaced by that median; plus P4. Return raw, corrected and indices.
- Quality: `no_ecg` if < 30 RR intervals; `poor` if artefacts > 5 %; else `good`.
- A 60-minute recording detects in under 10 s on the worker.

**Tests:**
- Synthetic ECG with known peaks at 60, 120 and 180 bpm: ±1 sample when clean, ±10 ms when noisy, no extra peaks.
- A motion-artefact spike: record how many beats are lost. If detection doesn't recover within a few beats, raise it with the product owner with the test as evidence; don't change the §6 method on your own.
- No RR across a gap; an ectopic beat is replaced.
- Boundaries: 20 % artefact, quality at 29/30 intervals and at 5 %.
- Property: corrected length = raw length; peaks strictly increasing and inside their segment.
- Performance test marked `slow`.

### SES-7 Heart rate, zones and training load · M · *blocked by P3*
**Acceptance criteria**
- 1 Hz HR series: from the HR file if present, else from corrected beats per P3; min/avg/max.
- Zones from `users.hr_max.resolve(...)`: below Z1 < 50 %, Z1 50–60, Z2 60–70, Z3 70–80, Z4 80–90, Z5 ≥ 90 (lower bound inclusive).
- Time in zones (s) and Edwards TRIMP = Σ minutes in zone × zone number.
- Implements `recompute_zone_metrics(user_id)` and `peak_max_hr(user_id)` from the stored 1 Hz HR, without re-running detection. Recompute resolves max HR per session (each has its own age and override) and updates both the stored analysis and the summary fields.

**Tests:** zone edges; time in zones sums to duration; TRIMP hand-computed; recompute changes stored analysis and summary values; recompute uses each session's own age.

### SES-8 HRV: time domain, frequency domain, Poincaré, respiration · L
**Acceptance criteria**
- HRV window per §6: the first 5 min (0–300 s) of the corrected RR series; shorter recordings use what exists.
- Time domain: mean RR, mean HR, SDNN (sample SD), RMSSD, pNNI20, pNNI50, beats.
- Lomb–Scargle PSD 0.002–0.5 Hz in 0.002 Hz steps, scaled so total power = RR variance. Bands VLF 0.0033–0.04, LF 0.04–0.15, HF 0.15–0.4 Hz with peak, power, %, n.u. (LF and HF only); LF/HF.
- Poincaré: SD1 = SD(ΔRR)/√2, SD2 = √(2·SDNN² − SD1²), SD1/SD2.
- Respiratory rate = HF peak × 60 (§6); per-minute series per P5.
- Fewer than 30 RR intervals in the window → HRV fields are null.

**Tests:** hand-computed RMSSD/SDNN/pNNI; sinusoidal RR gives the right HF peak and respiratory rate; total power ≈ variance; band % sums to 100; property tests from `CLAUDE.md`.

### SES-9 Movement load · S · *blocked by P5, P6*
**Acceptance criteria**
- Movement load per §6: Σ √(Δx² + Δy² + Δz²) / 100 over tri-axial acceleration (g), in AU, from an ACC file or from the hex file if it carries x/y/z (P6). Per-minute series per P5.
- No usable movement data → `movementLoad: null` everywhere.

**Tests:** hand-computed small series; null without movement data; per-minute series sums to the total.

### SES-10 Pipeline assembly and persistence · M
**Acceptance criteria**
- `analysis/pipeline.py` composes SES-4 to SES-9 into one `Analysis` + `Signals` result.
- `Signals`: 1 Hz HR; raw and corrected RR for the HRV window; artefact indices; first 10 s of ECG with R-peak indices (null without ECG); per-minute series.
- The worker saves results and summary fields (`avgHr`, `maxHr`, `rmssd`, `trainingLoad`, `movementLoad`, `quality`, `artefactCount`, `artefactPct`, `durationS`), replacing SES-3's stub pipeline.
- After a session becomes `ready`: if the user's max-HR method is `peak` and their peak changed, call `recompute_zone_metrics(user_id)` so their other sessions use the new peak.

**Tests:** golden tests on synthetic fixtures: a clean hex file; a noisy hex file with artefacts, a motion spike and a gap; an ECG CSV; RR-only without movement data. A new session with a higher max HR updates the zones and TRIMP of the user's earlier sessions when the method is `peak`, and leaves them alone otherwise.

### SES-11 Read APIs — `GET /sessions`, `/sessions/{id}/analysis`, `/sessions/{id}/signals` · M
**Acceptance criteria**
- List:
  - only sessions the caller can see, newest first
  - filters `userId`, `q` (email, file name, type)
  - `limit` 1–200 (default 50) and `offset`
  - `stats` over all visible filtered rows: sessions, users, recorded time, avg RMSSD ignoring nulls
- Analysis and signals: 404 for an unknown or invisible id; 409 `not_ready` unless `ready` (the message includes the status).

**Tests:** ordering; each filter; pagination; stats over the filtered set, not the page; a `user` never sees another user's sessions in the list or stats; admin sees all; 409 and 404; 401 without a token; responses match the schema.

### SES-12 Report PDF — `GET /sessions/{id}/report` · M
**Acceptance criteria**
- Returns `application/pdf`, filename `netribeat-<session-id>-<date>.pdf` (no email in the filename).
- Mirrors the Session view: header, KPI tiles, HR over time with zones, zone split, HRV tables, PSD and Poincaré charts, load and respiration, artefact note.
- Built from stored results only; 404 if not visible; 409 unless `ready`.

**Tests:** returns a valid PDF containing the expected title text; 404 for another user's session; 409; doesn't trigger analysis.

### SES-13 Delete a session — `DELETE /sessions/{id}` · S
**Acceptance criteria**
- Admin only (403 for `user`); unknown id → 404; 204 on success.
- Deletes the session, its results and its stored files. If the user's method is `peak` and their peak changed, calls `recompute_zone_metrics(user_id)`.
- Also implements `delete_sessions_for_user(user_id)` for USR-5.

**Tests:** files removed from storage; `user` gets 403; 404; deleted session gone from the list and stats; deleting the session that held the peak lowers the other sessions' max HR when the method is `peak`.

### SES-14 Validation against Kubios · M
**As the** product owner, **I want** NetriBeat's numbers checked against Kubios on real recordings **so that** we can call it Kubios-equivalent.

**Acceptance criteria**
- 5–10 anonymised recordings agreed with the product owner, covering rest and exercise, clean and noisy.
- Each is processed in Kubios with settings matched to NetriBeat's (spectrum method, detrending, artefact correction, window), and the Kubios settings are written down.
- A script runs NetriBeat on them and reports agreement per metric (RMSSD, SDNN, pNNI50, LF, HF, LF/HF, SD1, SD2, beat count).
- Tolerances agreed with the product owner and recorded in design-spec §6; any metric outside tolerance gets a bug ticket.
- The recordings stay outside the repo (personal data); only the script and the summary table are committed.

**Tests:** the script's comparison logic is unit-tested on synthetic data.

### SES-15 FIT / HRM / EDF parsers · M · *Track A, week 9*
Same contract as SES-5 for `.fit` (Garmin), `.hrm` (Polar) and `.edf`. Until it ships, these uploads fail with "Format not supported yet".

**Tests:** one small synthetic or anonymised fixture per format.

---

## Suggested order

| Weeks | Track A | Track B |
|---|---|---|
| 1–2 | BE-0.1, BE-0.2, AUTH-1, AUTH-2, AUTH-3 | SES-0, SES-4 (pure code; no scaffold needed), then SES-1 once BE-0.1 lands |
| 3–4 | USR-1, USR-2, AUTH-4, AUTH-5, USR-3 | SES-2, SES-3 (with the stub pipeline), SES-11. **The frontend can integrate upload, polling and the session view from here.** |
| 5–6 | USR-4, USR-5, contract-test hardening | SES-6, SES-7, start SES-8 |
| 7–8 | SES-5, SES-12 | Finish SES-8, SES-9, SES-10 (real pipeline replaces the stub), SES-13 |
| 9 | SES-15, buffer | SES-14 |

Track B starts with the hex file because every later stage depends on getting the ECG out of it correctly. The request side (upload, jobs, read APIs) comes next so the frontend isn't waiting on the analysis. P1 and P2 are needed in week 1; P3–P6 by week 5. USR-4 can be built against a stub `recompute_zone_metrics` until SES-7 lands in weeks 5–6.

## Open questions

Decided (written into *Users and roles*): a `user` uploads only for their own email and sees only their own data; admins upload for anyone and see everything; URLs use user ids, not emails. Revisit these before BE-0.2 if they're wrong.

1. **User details:** is email + age enough, or do we need name, sport or sex (e.g. for other max-HR formulas)?
2. **Email provider** for password reset (AUTH-4).
3. **Data retention and consent:** who signs off on how long recordings are kept and how people consent? (USR-5 makes deletion possible.)
4. **Coach-style access:** if someone later needs to see a group of users without being a full admin, that's a new role or a group feature. Out of scope for v1.
