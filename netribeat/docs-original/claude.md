# CLAUDE.md — NetriBeat

Heart rate, training load and HRV analysis from ECG chest-strap recordings.
This file tells Claude (and humans) how to work in this repo. Read it before writing code.

## Processing flow

```
ECG sensor ─► hex file ─► ECG signal extraction ─► R-peaks ─► RR intervals ─► derived metrics
```

| Stage | Module | Defined in |
|---|---|---|
| Read the hex file, extract the ECG signal into segments | `parsers/hex.py` | `docs/sensor-formats.md` |
| Detect R-peaks | `analysis/rpeaks.py` | design-spec §6 R-peak detection |
| RR intervals, artefacts, quality | `analysis/rr.py`, `artefacts.py`, `quality.py` | §6 RR, Artefact correction, Signal quality |
| HR, zones, training load, movement | `analysis/hr.py`, `zones.py`, `movement.py` | §6 |
| HRV and respiratory rate | `analysis/hrv_time.py`, `hrv_freq.py`, `poincare.py` | §6 |

RR, ECG, HR and ACC files (design-spec §3.3) enter through `parsers/` and join the same stages.

## Sources of truth

| What | Where | Rule |
|---|---|---|
| API contract | `docs/api-spec.yaml` (OpenAPI 3.0) | Endpoints, schemas, status codes and field names come from here. |
| Formulas and constants | `docs/design-spec.md` → §6 *Metric definitions* | Every metric is computed exactly as written there. |
| Sensor file format | `docs/sensor-formats.md` | Hex file header, packet layout, ECG sampling rate and units, gap and restart markers. |
| UI behaviour | `prototype/netribeat.html` + `docs/design-spec.md` | The frontend renders; it never computes metrics. |
| Backlog | `docs/backend-stories.md` | One story per PR where possible; reference the story ID. |

**If the spec doesn't say it, don't invent it.** For a missing formula, constant, threshold, field or status code, stop and ask. If a change to behaviour is agreed, update the spec file **in the same PR** as the code. When the spec and the prototype disagree, the spec wins; flag the difference.

## Domain vocabulary

- **User**: every person in the system. Identified internally by `id` (UUID); `email` (trimmed, lower-cased, unique) is for signing in and lookup. Has age and a max-HR setting. There is one kind of user; there are no separate profiles.
- **Role**: `user` or `admin`. Admins see all users and sessions, can upload for anyone, and are the only ones who can delete.
- **How users are created**: by an admin with `netribeat create-user`, or automatically when an admin uploads a session for an email that doesn't exist yet. An upload-created user has no password; they get a login through "forgot password". There is no sign-up screen.
- **Uploading**: a `user` uploads only for their own email; an `admin` uploads for any email.
- **Hex file**: the file the ECG sensor produces. Its layout is in `docs/sensor-formats.md`; nothing about it is guessed.
- **Segment**: a stretch of ECG without a gap. R-peaks are detected per segment, and RR intervals never span a gap.
- **Session**: one uploaded recording, tracked to a user (`user_id`), with `uploadedBy` = the signed-in user who uploaded it.
- **Visibility**: a `user` sees only sessions tracked to them and only their own profile. An `admin` sees everything.
- **HRmax resolution**: user's saved setting → session's upload override (`hrMaxManual`) → `210 − age`, where *age* is the **session's** age at recording, not the user's current age.
- **Peak max HR**: the highest `maxHr` across a user's `ready` sessions.
- **HRV window**: as defined in design-spec §6 (currently the first 300 s of the *corrected* RR series).
- Session `status`: `processing` → `ready` | `failed`. Analysis endpoints return **409** unless `ready`.

## Stack

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.0 (async) + Alembic · PostgreSQL · NumPy/SciPy · Arq + Redis (background analysis jobs) · PyJWT + argon2-cffi · WeasyPrint (PDF report) · uv · ruff · mypy · pytest + hypothesis + schemathesis.

Do not add a dependency without saying why in the PR description. Prefer NumPy/SciPy over new signal libraries.

## Commands

```bash
cd backend
uv sync                                   # install
docker compose up -d db redis             # local Postgres + Redis
uv run alembic upgrade head               # migrate
uv run uvicorn netribeat.main:app --reload
uv run arq netribeat.sessions.jobs.WorkerSettings   # analysis worker
uv run netribeat create-user --email … --name … --role admin   # first login

uv run pytest                             # all tests
uv run pytest tests/unit -q               # fast loop
uv run ruff check . && uv run ruff format --check .
uv run mypy src
make check                                # lint + types + tests; must pass before "done"
```

## Layout

```
backend/
  src/netribeat/
    main.py            app factory, routers, exception handlers
    config.py          pydantic-settings (env vars only, no secrets in code)
    db.py              engine, session dependency
    errors.py          AppError hierarchy → Error schema
    api_model.py       ApiModel base (camelCase aliases)
    cli.py             create-user, set-role, disable-user
    auth/              router · service · models · schemas · security · deps
    users/             router · service · models · schemas · hr_max.py
    sessions/          router · service · models · schemas · storage · jobs
    parsers/           PURE: detect_kind · hex · rr · ecg · hr · acc · errors
    analysis/          PURE: constants · rpeaks · rr · artefacts · hr · zones
                       · hrv_time · hrv_freq · poincare · movement · quality · pipeline
    reports/           pdf
  tests/
    unit/              analysis/, parsers/, services with fakes
    api/               HTTP tests through the app
    contract/          responses vs docs/api-spec.yaml
    golden/            whole-pipeline tests
    fixtures/          small synthetic recordings (hex, csv/txt) + golden/*.json
    factories.py       make_user(), make_admin(), make_session(), hex_file(), rr_series(), ecg_signal()
```

## Architecture rules

1. **Layers go one way:** `router → service → repository/models`. Routers parse input, call one service function and return a schema. No SQL and no business logic in routers.
2. **`parsers/` and `analysis/` are pure.** They take bytes, NumPy arrays and plain values and return dataclasses. No FastAPI, SQLAlchemy, storage access, logging config or `datetime.now()`. This is what makes them testable and reusable in the worker and the report.
3. **All constants live in `analysis/constants.py`** (file-format constants in `parsers/constants.py`), named and commented with the design-spec reference (e.g. `ARTEFACT_THRESHOLD = 0.20  # §6 Artefact correction`). No magic numbers elsewhere.
4. **Features talk through service functions, not each other's models.** Sessions calls `users.service.upsert_user(...)` and `users.hr_max.resolve(...)`; users calls `sessions.service.recompute_zone_metrics(...)`. Don't import another feature's ORM models or repositories.
5. **Never run signal processing inside a request.** Upload stores files, enqueues `analyse_session(session_id)` and returns 202. The worker sets `ready` or `failed` (+ `error`). Jobs must be idempotent: re-running one overwrites its results.
6. **Store derived results, don't recompute on read.** The worker persists analysis + signals; GET endpoints only read. Zone-dependent fields (max HR, zones, time in zone, TRIMP) are recomputed from the stored 1 Hz HR series, without re-running beat detection, whenever a user's max HR can change:
   - the user saves a new max-HR setting;
   - the user's method is `peak` and a session becoming `ready` or being deleted changes their peak.
7. **File storage goes through `sessions/storage.py`** (local disk in dev, object storage later). Nothing else touches paths.
8. **Access checks live in services, not routers.** Every service query that returns sessions or users takes the signed-in user and applies the visibility rule. A `user` asking for someone else's session or profile gets **404**, so the API never reveals what exists.
9. **Sampling rates are explicit.** Every signal carries its `fs` (or its timestamps), and sample counts are converted to time in one place. No bare numbers that silently mean milliseconds at one particular rate.
10. **Detection runs over each whole segment**, never in fixed-size chunks (chunks reset the detector and lose beats at the edges). **No RR interval spans a gap** or a missing sample.
11. **Raw uploads are stored unchanged**, so any session can be re-analysed after an algorithm change.
12. **Roles come from the database, not the token.** `current_user` loads the user on every request and uses its stored `role` and `is_active`. `token_version` is incremented on password reset, role change and disable, which signs out every existing token.

## API conventions

- Base path `/api/v1`. JSON is camelCase; Python is snake_case. All schemas extend `ApiModel` (`alias_generator=to_camel`, `populate_by_name=True`); responses serialise `by_alias`.
- Units are in field names exactly as the spec has them: `…S` seconds, `…Ms` milliseconds, `…Hz`. HR in bpm, loads in AU, power in ms². Don't round numbers in the API; formatting is the frontend's/PDF's job.
- Emails are normalised (`strip().lower()`) at the boundary, once, in a shared validator.
- Errors always use the `Error` schema: `{code, message, fields?}`. Raise `AppError` subclasses (`NotFound`, `ValidationFailed`, `Conflict`, `Unauthorized`, `Forbidden`, `PayloadTooLarge`); the global handler maps them. Override FastAPI's default 422 to return **400** `validation_error` with `fields`.
- Enum values are the API strings in design-spec §5 (`training`, `chest_strap_rr_acc`, `no_ecg`, …). Use `StrEnum`.
- Times are timezone-aware UTC in the DB; accept any offset on input.
- Every endpoint needs a signed-in user except `/auth/login`, `/auth/forgot-password`, `/auth/reset-password` and `/health`. Deletes need the `admin` role.
- Session and user ids are UUIDs. **Emails never appear in URL paths**: user endpoints are `/users/{id}`, and the sessions filter is `userId`. Emails go in request bodies, or in a `q` search parameter (query strings are left out of access logs).
- While a session is `processing`, `GET /sessions/{id}` sends `Retry-After: 2`.

## Data protection

Recordings are personal health data.

- **Never commit real user data**: no recordings, emails, names or screenshots of them in code, fixtures, docs, issues or PRs. Test fixtures are synthetic, or anonymised with written consent.
- **Hex file headers may contain personal details.** The parser keeps only the fields the analysis needs (listed in `sensor-formats.md`); everything else is discarded and never stored, logged or returned. The raw file itself stays in private storage.
- **Secrets only in environment variables.** Never commit `.env`; keep `.env.example` up to date with dummy values.
- **Logs carry ids, not personal data** (`session_id=…`, `user_id=…`). Never log passwords, tokens, emails or raw signals. Access logs record the path without the query string.
- Login and forgot-password are rate-limited (counters in Redis).
- API error messages never include stack traces, file paths or other people's data.

## Code style

- Type hints everywhere; `mypy --strict` on `analysis/` and `parsers/`. Arrays are `npt.NDArray[np.float64]`.
- Small functions with one job. A function that needs a comment to explain *what* it does should be split; comments explain *why*.
- Vectorise with NumPy; no Python loops over samples unless the algorithm requires state (e.g. a refractory period), and then say so.
- Don't catch broad exceptions except at the job boundary, where the error is logged and saved as `failed` with a user-readable `error`.
- Log with `structlog`-style key/values (`session_id=…`).
- Migrations: one Alembic revision per model change, autogenerate then read and fix it. Never edit a merged migration.

## Testing

Tests are part of the feature, not a follow-up. A PR without tests for new behaviour is not done.

### What to test where

| Layer | Test type | Speed | Notes |
|---|---|---|---|
| `parsers/` (incl. hex), `analysis/`, `users/hr_max.py` | Unit (pure) | ms | Most tests live here. Known-answer + property tests. |
| Services | Unit with fakes / test DB | fast | Business rules: HRmax resolution order, upsert, recompute, visibility. |
| Routers | API tests via `httpx.AsyncClient` | fast | Status codes, auth, validation messages, response shape. |
| Whole pipeline | Golden tests | seconds | Synthetic hex file or recording in → full Analysis JSON out. |
| Contract | Schema validation | seconds | Responses match `docs/api-spec.yaml`. |

### Analysis: known-answer tests first

Build inputs where the right answer is known by hand or by construction. Examples to copy:

```python
def test_rmssd_hand_computed():
    rr = np.array([800.0, 810.0, 790.0, 820.0])        # diffs 10, -20, 30
    assert rmssd(rr) == pytest.approx(np.sqrt((100 + 400 + 900) / 3))

def test_constant_rr_has_zero_variability():
    rr = np.full(300, 1000.0)
    td = time_domain(rr)
    assert td.rmssd == 0 and td.sdnn == 0 and td.mean_hr == pytest.approx(60)

def test_hf_peak_matches_breathing_frequency():
    rr = rr_series(mean_ms=900, modulation_hz=0.25, amplitude_ms=40, duration_s=300)
    fd = frequency_domain(rr)
    assert fd.bands.hf.peak_hz == pytest.approx(0.25, abs=0.004)  # 2 freq steps
    assert respiratory_rate(fd).value == pytest.approx(15, abs=0.3)

def test_single_ectopic_beat_is_replaced_by_local_median():
    rr = np.full(50, 800.0); rr[25] = 480.0             # 40 % short
    out = correct_artefacts(rr)
    assert out.indices.tolist() == [25] and out.corrected[25] == 800.0

def test_edwards_trimp_ten_minutes_in_z3():
    assert edwards_trimp({"z3": 600.0}) == pytest.approx(30.0)
```

Also always cover:
- **Boundaries** from the spec: 50 %/60 %/…/90 % HRmax (which zone owns the edge), artefact exactly 20 %, 29 vs 30 RR intervals for `no_ecg`, artefacts exactly 5 % for `poor`, HRmax 100 and 230, age 8 and 100.
- **Degenerate input**: empty arrays, recordings shorter than the HRV window, no ACC file (movement load `null`), NaNs and blank lines in input files.
- **Hex decoding**: build files with `factories.hex_file()` from a known ECG signal and check that decoding gives it back; cover gaps (exactly at and just over the threshold), duplicate, out-of-order and corrupted packets, restarts, header-only and empty files. Never use a real recording as a fixture.
- **R-peak detection**: synthesise ECG from known R-peak times (`factories.ecg_signal(peaks_s, fs, noise=…)`) and assert every detected peak is within ±1 sample (clean) or ±10 ms (noisy), with no extra peaks. Include a motion-artefact spike: detection must recover after it.

### Property tests (hypothesis)

Use them for invariants, not exact values:
- Corrected RR has the same length as raw RR.
- Time in zones sums to the recording duration.
- `0 ≤ pnni50 ≤ pnni20 ≤ 100`; band `powerPct` values sum to 100.
- Scaling all RR by k scales RMSSD and SDNN by k.

### Tolerances

- Exact formulas: `pytest.approx` / `np.testing.assert_allclose(rtol=1e-9)`.
- Spectral and detection results: tolerance tied to resolution (PSD step 0.002 Hz, one ECG sample), written as a named constant in the test, never a bare `0.1`.

### Golden tests

- Fixtures in `tests/fixtures/recordings/` (synthetic; keep each < 200 kB). Expected output in `tests/fixtures/golden/<name>.json`.
- The test runs the full pipeline and compares with `assert_allclose(rtol=1e-6)` field by field.
- Regenerate only with `uv run pytest tests/golden --update-golden`; the JSON diff must be reviewed in the PR and the reason stated. A golden change with no stated reason is a bug.
- Golden tests catch *changes*, not *errors*. Agreement with Kubios on real recordings is checked separately (story SES-14).

### API tests

- Fixtures in `tests/conftest.py`: `client` (AsyncClient on the app), `db` (each test in a transaction that is rolled back), `auth_headers(user)`, `admin_headers`, `storage` (on `tmp_path`), `run_jobs_inline` (the job queue runs the analysis synchronously so upload → ready works in one test).
- For each endpoint, test: happy path, 401 without a token, 403 for a `user` where admin is required (or when uploading for another email), 404 when a `user` asks for someone else's data, each 4xx in the spec (400 with the `fields` message, 404, 409, 413, 429), and the response against the schema.
- Assert on the API (status, JSON) only, never on internal state the client can't see, except where a story says "persisted".

### Contract tests

- `tests/contract/` loads `docs/api-spec.yaml` and validates real responses (schemathesis or openapi-core).
- A test fails if the app has a route that is not in the spec or the spec has a path the app doesn't implement (`/health` excepted).

### Test rules

- Arrange / Act / Assert; one behaviour per test; name it `test_<unit>_<behaviour>`.
- Deterministic: seed every RNG (`np.random.default_rng(42)`), freeze time, no network, no real email (use the fake sender).
- Unit suite runs in under 10 s. Mark slow tests `@pytest.mark.slow`.
- Every bug fix starts with a failing test that reproduces it.
- Coverage: ≥ 95 % lines on `analysis/` and `parsers/`, ≥ 85 % overall. Coverage is a floor, not the goal.
- Use `tests/factories.py`; don't hand-build the same objects in many tests.

## Git workflow

- One branch per story, named `<story-id>-<short-name>` (e.g. `ses-6-beat-detection`).
- **Never push to `main` and never merge.** Open a pull request; people review and merge.
- One story per PR. The description says what changed, which acceptance criteria are met, how it was tested, and any spec change.
- Rebase on `main` before asking for review, so `main` stays green.

## Definition of done

- [ ] Behaviour matches the story's acceptance criteria and the spec.
- [ ] Tests added per the table above; `make check` passes.
- [ ] `docs/api-spec.yaml` / `docs/design-spec.md` updated if the contract or a formula changed.
- [ ] Migration added and checked if models changed.
- [ ] No real user data, no secrets, no TODOs without a story ID.

## How Claude should work here

- Before coding, read the story, the matching parts of the specs (`api-spec.yaml`, design-spec, `sensor-formats.md`) and the existing code in that feature folder.
- Write or update tests alongside the code, and run them. Report what was run and the result; don't claim something passes without running it.
- Keep changes inside the story's scope. Note anything else you notice in the PR description instead of fixing it.
- When the spec is silent or contradicts itself, stop and ask; don't guess a formula or threshold.
