# Free deployment: Vercel + Render + Neon + Brevo + UptimeRobot

No program changes. One configuration file (`frontend/vercel.json`) and environment
variables. Total cost: €0. Free-tier terms were checked in October 2026 and change
often, so re-check the providers' pages if something behaves differently.

```
Browser ── https://netribeat.vercel.app ──▶ Vercel (React app; forwards /api/* ↓)
                                             ▼
                          Render free web service (FastAPI, Docker, analysis inside)
                             │                         │                     │
                     Neon PostgreSQL          Render Key Value (Redis)   Brevo SMTP :2525
                    (free, doesn't expire)    (rate limits)              (emails)
UptimeRobot ── pings /api/v1/health every 5 min so Render doesn't fall asleep
```

## Why these choices (checked against current limits)

| Need | Choice | Why not the obvious alternative |
|---|---|---|
| PostgreSQL | **Neon free**: 0.5 GB, doesn't expire, sleeps after 5 min idle | Render's free PostgreSQL is **deleted 30 days after creation** |
| Email | **Brevo free** (300 per day) on **port 2525** | Render's free tier **blocks ports 25, 465 and 587** (since Sept 2025); Brevo officially offers 2525 as the fallback |
| Backend | Render free web service (512 MB, 0.1 CPU) | Render offers no free background workers, so analysis runs inside the web service (`JOB_BACKEND=inline`) |
| Frontend | Vercel (static + rewrite) | The rewrite keeps the site and `/api` on one domain, so the secure login cookie works unchanged |

**Measured memory:** the app uses about 180 MB; analysing your largest file (14 MB ECG
CSV) peaks at 423 MB. That fits 512 MB **only with `WEB_CONCURRENCY=1`**.

## What you must accept on the free tier

| Limit | Effect on NetriBeat | Workaround |
|---|---|---|
| The server sleeps after 15 min without traffic (about 1 min to wake) | The first visit is slow | UptimeRobot (step 7) keeps it awake; 1 service × 24 h ≈ 744 h, within the 750 free hours/month |
| The disk is wiped on every restart/redeploy | **Analysis results are safe** (they're in Neon), but **"Original file" downloads and "Retry" stop working** for older sessions | Keep your own copies of uploaded files |
| 0.1 CPU | Analysis takes about 5–20 s per file | Upload large ECG files **one at a time** (several at once can run out of memory) |
| No background worker | If Render restarts during an analysis, that session stays "processing" | Delete it and upload again |
| `ENVIRONMENT=development` is required (production mode insists on a worker) | Production's safety *check* is skipped, but each safety *setting* is set explicitly below | Set every variable in step 5 exactly as shown |
| Per-IP rate limits behind two proxies can't see the true client IP reliably | Per-email login limits still work | — |
| Uploads through Vercel's rewrite | Vercel documents a 4.5 MB body limit for its *Functions*; a limit for external rewrites isn't documented. RR files are tiny; large ECG files might be refused | If a large upload returns 413, upload it on your PC version or move to the Docker server guide |
| Neon free = 0.5 GB | Roughly a few thousand sessions (results take ~30 KB–1 MB each) | Delete old sessions, or upgrade |

## Step 1: put the project on GitHub (PowerShell)

Install Git from <https://git-scm.com/download/win>. Create an **empty private**
repository on GitHub named `netribeat` (no README). Then:

```powershell
cd D:\sivanesh\netribeat\netribeat
git init
git add .
git status            # check that NO ".env" file is listed (it must stay secret)
git commit -m "NetriBeat"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/netribeat.git
git push -u origin main
```

`.gitignore` already excludes `.env`, `.venv`, `node_modules` and the stored files.

## Step 2: PostgreSQL on Neon

1. Sign up at <https://neon.com> and **Create project**: name `netribeat`, PostgreSQL
   17, region **AWS Asia Pacific (Singapore)** (closest to you; use the same region on
   Render).
2. On the dashboard, open **Connect**, **turn the "Connection pooling" switch OFF**
   (NetriBeat's driver needs the direct endpoint; its host has no `-pooler` in it),
   and copy the connection string. It looks like:
   `postgresql://neondb_owner:PASSWORD@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require`
3. **Convert it for NetriBeat.** Change the start to `postgresql+asyncpg://`, and
   replace everything after `?` with `ssl=require`:
   `postgresql+asyncpg://neondb_owner:PASSWORD@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?ssl=require`
   (Tested: `sslmode=…` makes the driver fail with *unexpected keyword argument
   'sslmode'*; `ssl=require` connects with TLS 1.3.)
4. **Create your admin from your PC** (PowerShell, in `backend`):

```powershell
cd D:\sivanesh\netribeat\netribeat\backend
$env:DATABASE_URL = "postgresql+asyncpg://neondb_owner:PASSWORD@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?ssl=require"
uv run netribeat create-admin --email you@example.org --first-name You --last-name Admin
Remove-Item Env:DATABASE_URL       # back to your local database
```

(The backend creates any missing tables itself every time it starts.)

**Optional: copy your existing local data to Neon.** Only analysis results move;
uploaded original files don't. If your local PostgreSQL runs in Docker
(`infra\docker-compose.yml`):

```powershell
cd D:\sivanesh\netribeat\netribeat\infra
docker compose exec postgres pg_dump -U netribeat -Fc -f /tmp/nb.dump netribeat
docker compose cp postgres:/tmp/nb.dump .\nb.dump
docker run --rm -v "${PWD}:/d" postgres:17-alpine pg_restore --no-owner --no-acl --clean --if-exists -d "postgresql://neondb_owner:PASSWORD@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require" /d/nb.dump
```

(Do **not** use `pg_dump … > file` in Windows PowerShell 5: `>` rewrites binary dumps
as text and corrupts them. Here `pg_restore` uses `sslmode=require`, because it's a
different client from NetriBeat.) Skip `create-admin` in step 4 if your admin came
across with the data.

**Backups:** Neon's free plan keeps a 6-hour restore window. For real backups, run the
same `pg_dump` against the Neon URL from your PC regularly, e.g. weekly:
`docker run --rm -v "${PWD}:/d" postgres:17-alpine pg_dump -Fc -f /d/neon-backup.dump "postgresql://…neon…/neondb?sslmode=require"`

## Step 3: email with Brevo

1. Sign up at <https://www.brevo.com> (free plan).
2. **Senders, Domains & Dedicated IPs → Senders:** add and verify the address you'll
   send from (e.g. your Gmail). With your own domain, also authenticate the domain
   (SPF/DKIM) so codes don't land in spam.
3. **SMTP & API → SMTP:** note the **login** (often `xxxx@smtp-brevo.com`) and
   **generate an SMTP key** (this is the password).
4. Use server `smtp-relay.brevo.com`, **port 2525**, STARTTLS.

## Step 4: Redis on Render (Key Value, free)

<https://dashboard.render.com> → **New → Key Value** → name `netribeat-redis`,
region **Singapore**, plan **Free** → Create. Copy the **Internal Key Value URL**
(`redis://red-xxxx:6379`).

## Step 5: the backend on Render

**New → Web Service** → connect GitHub → choose `netribeat` → then:

| Setting | Value |
|---|---|
| Language | **Docker** |
| Region | **Singapore** (same as Neon and Key Value) |
| Branch | `main` |
| Root Directory | *(leave empty)* |
| Dockerfile Path | `infra/Dockerfile.backend` |
| Docker Build Context Directory | `.` |
| Instance Type | **Free** |
| Health Check Path | `/api/v1/health` |

**Environment variables** (Advanced → Add from .env, or one by one). Generate the two
secrets on your PC with `uv run python -c "import secrets; print(secrets.token_urlsafe(48))"`,
running it twice to get two different values.

```
PORT=8000
WEB_CONCURRENCY=1
ENVIRONMENT=development
API_DOCS_ENABLED=false
COOKIE_SECURE=true
DATABASE_URL=postgresql+asyncpg://neondb_owner:PASSWORD@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?ssl=require
REDIS_URL=redis://red-xxxx:6379
JWT_SECRET=<first generated secret>
OTP_PEPPER=<second, different generated secret>
FRONTEND_BASE_URL=https://netribeat.vercel.app
CORS_ORIGINS=https://netribeat.vercel.app
EMAIL_BACKEND=smtp
EMAIL_FROM=NetriBeat <the-sender-you-verified@example.com>
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=2525
SMTP_STARTTLS=true
SMTP_SSL=false
SMTP_USERNAME=<Brevo SMTP login>
SMTP_PASSWORD=<Brevo SMTP key>
HIBP_CHECK_ENABLED=true
LOG_LEVEL=INFO
```

Use your real Vercel address in `FRONTEND_BASE_URL` and `CORS_ORIGINS` (you'll know it
after step 6; come back and update them, and Render redeploys).

Create the service. The first build takes several minutes. In **Logs** you should see
`Running upgrade …` (or nothing new if step 2 already ran it) and `Application startup
complete`. Note the URL, e.g. `https://netribeat-api.onrender.com`. Check
`https://netribeat-api.onrender.com/api/v1/health/ready` → `"database":"ok","redis":"ok"`.

## Step 6: the frontend on Vercel

1. In `frontend/vercel.json`, replace `YOUR-RENDER-SERVICE` with your Render
   service name (e.g. `netribeat-api`), then commit and push:

```powershell
cd D:\sivanesh\netribeat\netribeat
git add frontend/vercel.json
git commit -m "Point Vercel at the Render API"
git push
```

2. <https://vercel.com> → **Add New → Project** → import `netribeat` →
   **Root Directory: `frontend`**, Framework Preset **Vite**, Build Command
   `npm run build`, Output Directory `dist` → **Deploy**.
3. Note your address (e.g. `https://netribeat.vercel.app`). Put it in Render's
   `FRONTEND_BASE_URL` and `CORS_ORIGINS` (step 5). They must match **exactly**,
   including `https://` and with no trailing `/`. Login is refused if they don't.

## Step 7: keep it awake with UptimeRobot

<https://uptimerobot.com> → **New monitor** → type **HTTP(s)** → URL
`https://netribeat-api.onrender.com/api/v1/health` → interval **5 minutes**.

Ping `/api/v1/health`, **not** `/health/ready`: plain `/health` doesn't touch the
database, so Neon can still sleep and save its 100 free compute-hours. Add a second
monitor for your Vercel address if you want alerts when the site is down.

## Step 8: test it like a new user

1. Open `https://netribeat.vercel.app/register`, register with a real email, and enter
   the code from the email.
2. Upload `D1BLHR_RR.csv`; it becomes "Ready" after about 5–20 s.
3. Download the PDF. Sign in on another device; use "Forgot password?".
4. `https://netribeat.vercel.app/admin/login` with the admin from step 2.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Render log: `unexpected keyword argument 'sslmode'` | `DATABASE_URL` still ends with `?sslmode=…`; use `?ssl=require` |
| Render log: `prepared statement … does not exist` | You copied the **pooled** Neon host (`-pooler`); turn pooling off and use the direct host |
| Render log: `JOB_BACKEND must be arq …` | `ENVIRONMENT` is `production`; on the free tier it must be `development` |
| No code emails arrive, log shows `email_delivery_failed` | Port isn't 2525; sender not verified in Brevo; check Brevo → Transactional → Logs and the spam folder |
| Login works but you're logged out on reload | `FRONTEND_BASE_URL`/`CORS_ORIGINS` don't exactly match the Vercel address |
| Sign-in fails with "Origin not allowed" (403) | Same as above |
| Every API call is 404 on Vercel | `vercel.json` still says `YOUR-RENDER-SERVICE`, or Root Directory isn't `frontend` |
| Upload of a large ECG returns 413 | Vercel's proxy body limit; see the limits table |
| Render restarts during uploads / "out of memory" | `WEB_CONCURRENCY` isn't `1`, or several large ECG files at once |
| `/health/ready` shows `redis: unavailable` | Wrong `REDIS_URL`, or Key Value in a different region |
| The site is slow on the first visit | Render was asleep; check that the UptimeRobot monitor is active |

## When to move off the free tier

When people depend on it daily: ~$7/month for Render's Starter instance removes the
sleep, unblocks SMTP and allows more memory. A small VPS with the
`docs/deployment.md` Docker setup gives you persistent file storage, a background
worker and production mode for about the same price.
