# NetriBeat

Heart rate, training load and HRV analysis from chest-strap recordings, with secure
multi-user accounts. You upload ECG or RR-interval files as **`.json`, `.csv` or
`.txt`**; the backend analyses them in the background and the dashboard shows the
results, including a **Kubios-style HRV report**.

**Input formats** (detected from the content, not the file name)
- **ECG:** Movesense JSON (`data[].ecg`) or Movesense CSV (`"Elapsed time","ECG"`).
- **RR intervals:** Movesense JSON (`data[].heartRate.rrData`); an RR list as CSV/TXT
  (one value per line, in ms or s, optional header; e.g. `D1BLHR_RR.csv`); or the same
  list as JSON: `[812, 790, …]` or `{"rr": [812, 790, …]}`. The CSV and JSON forms of
  one recording give identical results.

**Features**
- **Accounts:** registration with an emailed code, user and admin sign-in, "keep me
  signed in", device sessions, forgot/reset password, admin user management, audit log.
  Administrators are created only by a server CLI.
- **Recordings:** upload up to 10 files at once (50 MB each); each file becomes one
  session. The format is detected from the file content. Your own data only; admins
  can see and upload for anyone.
- **Analysis (design-spec §6):** R-peak detection, artefact correction, signal quality,
  1 Hz heart rate, HR zones and Edwards TRIMP, HRV time domain (RMSSD, SDNN, pNNI20/50),
  Lomb–Scargle frequency domain (VLF/LF/HF, LF/HF), Poincaré SD1/SD2, respiratory rate.
  Runs in a durable background worker.
- **Screens:**
  - Dashboard with trends.
  - Upload page with progress.
  - Sessions list.
  - Session view with five tabs (Overview, ECG & beats, Heart rate, HRV, Load &
    respiration) and interactive charts.
  - Max HR settings (recalculates zones and load for your sessions).
  - Profile and Security (devices, password), plus admin Users and Audit log.
- **Advanced HRV (Kubios-compatible definitions):** sample selection, threshold artefact
  correction (very low → very strong), smoothness-priors detrending, time domain (incl.
  NN50, pNN50, triangular index, TINN, stress index), FFT/AR/Lomb–Scargle spectra,
  Poincaré, ApEn, SampEn, DFA α1/α2, recurrence plot, time-varying HRV, and ANS
  components. Re-run with your own options from the session page. See
  [`docs/analysis.md`](docs/analysis.md) for what is and isn't implemented.
- **Reports:** a PDF whose first page is an HRV results sheet in the Kubios layout, then
  NetriBeat's own pages; CSV exports (metrics, 1 Hz HR, beats, spectrum) and a full
  JSON export with provenance, all generated from stored results.
- **Production:** Docker images, Caddy with automatic HTTPS, a production Compose stack
  with a worker and persistent storage. **To put it online:
  [`docs/deployment.md`](docs/deployment.md).**

**Read this before relying on the numbers:** [`docs/analysis.md`](docs/analysis.md).
The specified R-peak detector works on clean recordings, where it matches the sensor's
own RR stream within 0.2 bpm and 0.6 % RMSSD. It fails on recordings with large motion
spikes, which are then clearly marked **unreliable**. Four rules (P2–P5) are
**provisional** until the product owner settles them. Results are research estimates,
not clinical measurements.

## What was verified

| Check | Result |
|---|---|
| Backend tests (real PostgreSQL 16 + Redis) | 296 passed, 92.4 % coverage |
| Lint and types | `ruff` and `mypy --strict`: clean |
| Migrations | Up → down → up cycle; `alembic check`: models and migrations agree |
| Dependency scan | `pip-audit` and `npm audit`: no known vulnerabilities (at packaging time) |
| Frontend tests | 45 passed (vitest + Testing Library); production build OK |
| Full production mode over HTTPS, RR files | Your 6 RR CSVs + the JSON uploaded and analysed by the worker in 3.2 s; re-analysis and the Kubios-style PDF (3 pages) verified |
| Full production mode over HTTPS, dataset | Real Caddy, `ENVIRONMENT=production`, real SMTP, the Arq worker as a separate process. All 10 supplied recordings (25.3 MB) uploaded in one request and analysed in about 3 s; PDF/CSV/JSON exports, Max HR recalculation and delete all worked; no secrets in any log |

These checks ran on Linux. The Windows steps follow standard tooling but weren't run on
Windows. The Docker images and Compose files weren't built (no Docker where this was
prepared); the same configuration was verified outside containers.

## Folder layout

```
backend/    FastAPI app: src/netribeat/{auth,users,sessions,parsers,analysis,reports}, migrations, tests
frontend/   React + Vite app (src/pages, src/charts, src/components, src/api, src/auth)
infra/      docker-compose.yml for local PostgreSQL + Redis
docs/       openapi.json, API notes, security model, dataset audit, task plan
docs-original/  the specification files you supplied (unchanged)
prototype/  the original HTML prototype (unchanged)
```

---

## Two ways to run it

- **On the internet for free** (Vercel + Render + Neon + Brevo + UptimeRobot, no code changes): [`docs/free-deployment.md`](docs/free-deployment.md).
- **On the internet, on your own server and domain:** [`docs/deployment.md`](docs/deployment.md). You need a Linux server, a domain and an SMTP account. Every command is run from Windows PowerShell over SSH.
- **On your own PC, for development and testing:** the steps below.

## Development setup on Windows 10/11 (PowerShell)

Open **PowerShell** for every command below. Lines starting with `#` are explanations; don't type them.

### 1. Install the tools (once)

1. **Python 3.12**: from <https://www.python.org/downloads/>. During setup, tick **"Add python.exe to PATH"**.
2. **uv** (the Python package manager this project uses):
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
   Close and reopen PowerShell afterwards, then check it with `uv --version`.
3. **Node.js 22 LTS**: from <https://nodejs.org/>. Check it with `node --version`.
4. **Docker Desktop**: from <https://www.docker.com/products/docker-desktop/>. Start it and wait until it says "Engine running".

If you would rather install PostgreSQL 16 and Redis yourself instead of using Docker, see "Without Docker" further down.

### 2. Start PostgreSQL and Redis

```powershell
cd path\to\netribeat\infra
copy .env.example .env
notepad .env          # set POSTGRES_PASSWORD to a long random value, then save
docker compose up -d  # starts PostgreSQL on 127.0.0.1:5432 and Redis on 127.0.0.1:6379
docker compose ps     # both services should show "healthy"
```

The first start also creates a second database, `netribeat_test`, for the automated tests.

### 3. Configure the backend

```powershell
cd ..\backend
copy .env.example .env
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"   # copy the output
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"   # copy this one too
notepad .env
```

In `.env`, set these values:
- `DATABASE_URL`: replace `CHANGE_ME_DB_PASSWORD` with the password you set in `infra\.env`.
- `JWT_SECRET`: paste the first generated value.
- `OTP_PEPPER`: paste the second generated value. It must be different from `JWT_SECRET`.

Leave `EMAIL_BACKEND=console` for now. Verification and reset codes will then be printed in the backend terminal instead of being emailed.

### 4. Install dependencies, create the tables, create the first admin

```powershell
uv sync                                   # installs the exact locked versions into backend\.venv
uv run alembic upgrade head               # creates the tables; prints "Running upgrade -> 0001 … 0002"
uv run netribeat create-admin --email you@example.org --first-name Your --last-name Name
# You will be asked for the password twice. It is never shown, and it is never a command
# argument, so it doesn't end up in your shell history.
```

**Administrators can only be created this way.** The public registration page always creates ordinary `user` accounts.

### 5. Run the backend

```powershell
uv run uvicorn --factory netribeat.main:app_factory --reload --port 8000
```

Leave this window open. API docs are at <http://localhost:8000/api/docs>, and the readiness check is at <http://localhost:8000/api/v1/health/ready>. It should show `database: ok` and `redis: ok`.

### 6. Run the frontend (in a second PowerShell window)

```powershell
cd path\to\netribeat\frontend
npm ci          # installs the exact locked versions
npm run dev     # serves http://localhost:5173 and forwards /api to the backend on :8000
```

Open <http://localhost:5173>.

### 7. Try it

1. **Create account**: fill in the form and submit.
2. Look in the **backend** window for a block marked `[DEV EMAIL — not sent]`. It contains a 6-digit code.
3. Enter the code on the verification page. You'll then be returned to sign in.
4. Sign in. The dashboard opens.
5. **New recording**: drop one or more of your `.json` / `.csv` files and select
   **Upload and analyse**. With the default `JOB_BACKEND=inline`, analysis runs inside
   the backend and finishes in seconds. Open a session to see the tabs; download the PDF
   or CSV/JSON from the bottom of the session page. For JSON files, enter the age at
   upload (JSON files contain no age), or set a manual max HR under **Settings**, so
   zones and training load can be computed.
6. **Forgot password?**: request a code (shown in the backend window again), enter it, and choose a new password. All your other sessions are signed out.
7. **Administrator sign in** (link under the sign-in form): use the account from step 4 of the setup. You'll see **Users** and **Audit log**.

### Optional: run analysis in a separate worker (as in production)

In `backend\.env` set `JOB_BACKEND=arq`, restart the backend, and in a third window run:

```powershell
cd path\to\netribeat\backend
uv run arq netribeat.sessions.worker.WorkerSettings
```

Uploads then return immediately with status "processing". The page updates on its own
when the worker finishes. If the worker isn't running, sessions stay "processing" until
it starts; nothing is lost.

### 8. Run the automated tests

```powershell
cd path\to\netribeat\backend
uv run pytest -q --cov         # uses the netribeat_test database (its tables are recreated)
uv run ruff check .
uv run mypy
cd ..\frontend
npm test
```

On macOS/Linux, `make check` in `backend/` runs lint, types, migration check and tests together.

### Sending real email (SMTP)

In `backend\.env`:

```
EMAIL_BACKEND=smtp
EMAIL_FROM=NetriBeat <no-reply@your-domain.org>
SMTP_HOST=smtp.your-provider.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_STARTTLS=true
```

Any SMTP provider works (SendGrid, Mailgun, Amazon SES, Postmark, Microsoft 365, …). For port 465, set `SMTP_SSL=true`. Restart the backend after any change.

### Useful CLI commands

```powershell
uv run netribeat list-admins
uv run netribeat create-user --email person@example.org --first-name A --last-name B   # no password; they use "Forgot password?"
uv run netribeat set-role --email person@example.org --role admin
uv run netribeat disable-user --email person@example.org   # signs them out everywhere
uv run netribeat enable-user --email person@example.org
uv run netribeat cleanup        # expire old codes and delete stale sign-ups/sessions (schedule daily)
```

### Without Docker

Install PostgreSQL 16 (<https://www.postgresql.org/download/windows/>) and a Redis-compatible server. On Windows, Memurai is one option; Redis is also available inside WSL. Then, as the `postgres` superuser in `psql`:

```sql
CREATE ROLE netribeat LOGIN PASSWORD 'your-long-password';
CREATE DATABASE netribeat OWNER netribeat;
CREATE DATABASE netribeat_test OWNER netribeat;
```

The application role is deliberately not a superuser.

### Troubleshooting

| Symptom | Fix |
|---|---|
| Backend exits with `JWT_SECRET must be at least 32 characters` | Generate the secrets as shown in step 3. The two secrets must be different. |
| `connection refused` on port 5432 or 6379 | Docker Desktop isn't running, or the containers aren't up. Run `docker compose ps` in `infra`. |
| `password authentication failed for user "netribeat"` | The password in `DATABASE_URL` doesn't match `infra\.env`. If you changed it after the first start, run `docker compose down -v` (**deletes the local data**) and start again. |
| Readiness shows `redis: unavailable`, and logins return 503 | Redis isn't running. Rate limiting fails closed by design. |
| "Can't reach the server" in the browser | The backend isn't running on port 8000. |
| Login works but the session is lost on reload | Open the site at `http://localhost:5173`, not `127.0.0.1:5173`, so the origin matches `CORS_ORIGINS`. |
| No verification code appears | With `EMAIL_BACKEND=console`, codes print in the **backend** window. Codes are also rate-limited: at most 3 per address per hour, and at least 60 s apart. |
| HTTP 429 | Too many attempts. Wait 15 minutes for logins, or 1 hour for code requests. |
| Sessions stay "processing" | With `JOB_BACKEND=arq`, the worker isn't running (see "Optional: run analysis in a separate worker"). |
| `create-admin` says "User already has a login" | That email already has an account (for example, you registered it on the website). Promote it instead: `uv run netribeat set-role --email you@example.org --role admin`, then use **Administrator sign in**. |
| Upload is rejected (the backend log shows `POST /api/v1/sessions … status=400`) | The reason is shown in red under each file on the upload page, and in the backend log as `upload_rejected reasons=…`. Check files from the command line with `uv run netribeat check-file "C:\path\to\file.json"`; it prints the detected format, quality, heart rate and any problem. |
| `warning: Failed to hardlink files; falling back to full copy` during `uv sync` | Harmless: the uv cache and the project are on different drives. To silence it, run `$env:UV_LINK_MODE = "copy"` first. |
| Upload says "format not recognised" | Run `uv run netribeat check-file <file>`; the supported formats are listed at the top of this README. HEX files need `docs/sensor-formats.md`. |
| Training load shows "—" | JSON files contain no age: enter the age at upload, or set a max HR in Settings. |
| A session says "Beat detection is unreliable" | Strong noise or motion spikes in the ECG; see docs/analysis.md. |

### macOS / Linux

The commands are the same except: use `cp` instead of `copy`, a text editor instead of `notepad`, and install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh`.

---

To deploy on a real domain, see [`docs/deployment.md`](docs/deployment.md). Don't expose the development setup (`npm run dev`, `uvicorn --reload`, `EMAIL_BACKEND=console`) to the internet. The security model and its current limits are in [`docs/security.md`](docs/security.md).
