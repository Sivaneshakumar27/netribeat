# Getting started

Run NetriBeat on your own computer. Commands are for Windows PowerShell; on macOS/Linux use
`cp` instead of `copy`.

[← Back to README](../README.md)

---

## 1. Install the tools

| Tool | Used for | Get it |
|---|---|---|
| Docker Desktop | Local PostgreSQL 16 and Redis 7 | <https://www.docker.com/products/docker-desktop> |
| uv | Python 3.12 and the backend's packages | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Node.js 22 | The frontend | <https://nodejs.org> |

## 2. Start PostgreSQL and Redis

```powershell
cd infra
copy .env.example .env          # set POSTGRES_PASSWORD to anything you like
docker compose up -d
```

Both listen on `127.0.0.1` only (ports 5432 and 6379).

## 3. Configure and start the backend

```powershell
cd ..\backend
copy .env.example .env
```

Edit `backend\.env`:

1. Put the password from step 2 into `DATABASE_URL`.
2. Generate **two different** secrets, one for `JWT_SECRET` and one for `OTP_PEPPER`:

   ```powershell
   uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

Leave `EMAIL_BACKEND=console`: verification and reset codes are printed in the backend window
instead of being emailed. Every setting is explained in [Configuration](configuration.md).

```powershell
uv sync
uv run uvicorn --factory netribeat.main:app_factory --reload
```

The tables are created automatically on start. Check <http://127.0.0.1:8000/api/v1/health/ready>
shows `"database": "ok"` and `"redis": "ok"`. Interactive API docs: <http://127.0.0.1:8000/api/docs>.

## 4. Create your admin

Administrators can only be created from the command line (never through the website):

```powershell
uv run netribeat create-admin --email you@example.org --first-name Your --last-name Name
```

You're asked for the password twice. Other commands:

| Command | Does |
|---|---|
| `netribeat create-user --email … --first-name … --last-name …` | Account without a password (the person uses *Forgot password*) |
| `netribeat set-role --email … --role user\|admin` | Change a role; signs the person out everywhere |
| `netribeat disable-user --email …` / `enable-user` | Block or unblock an account |
| `netribeat list-admins` | List administrators |
| `netribeat cleanup` | Delete expired codes, sign-ups and sessions (run daily) |

## 5. Start the frontend

In a second window:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The dev server forwards `/api` to the backend, so the browser sees
one site and the sign-in cookie works.

## 6. Try it

1. **Register** at `/register` → the code appears in the backend window → enter it.
2. **Upload** a Synapse hex file at *New recording*. Fill in age and gender for zones and
   training load (or set them once in *Profile*).
3. **Open the session** → tabs for overview, beats, heart rate, HRV and load.
4. **Download the PDF** under *Report and exports*.
5. **Admin**: sign in at `/admin/login` with the account from step 4.

## Checks before committing

```powershell
# backend
cd backend
uv run ruff check .;  uv run ruff format --check .;  uv run mypy
# frontend
cd ..\frontend
npm test;  npm run build
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/health/ready` shows `database: unavailable` | Docker isn't running, or the password in `DATABASE_URL` differs from `infra\.env` |
| `redis: unavailable` / every login returns 503 | Redis isn't running (`docker compose up -d`); sign-in refuses to work without rate limiting |
| Backend refuses to start: `JWT_SECRET must be…` | Secrets must be ≥ 32 characters and different from each other |
| No verification code | With `EMAIL_BACKEND=console` it's printed in the **backend** window |
| Upload says *Not a usable Synapse hex file* | The file isn't a Synapse hex export (one 200-character packet per line) |
| Training load shows "—" | Enter age, and gender male or female, on the upload form or in *Profile* |
