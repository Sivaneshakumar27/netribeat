# Deployment

The live setup: **Vercel** (website) → **Render** (backend) → **Neon** (database), with Redis on
Render and email through **Brevo**.

[← Back to README](../README.md)

---

```mermaid
flowchart LR
    B[Browser] --> V[Vercel<br/>React app]
    V -->|/api/* rewrite| R[Render<br/>Docker: infra/Dockerfile.backend]
    R --> N[(Neon PostgreSQL)]
    R --> K[(Render Key Value<br/>Redis)]
    R -->|SMTP :2525| E[Brevo]
    U[UptimeRobot] -.->|/api/v1/health every 5 min| R
```

Every push to `main` on GitHub redeploys Render and Vercel automatically.

## 1 · Database — Neon

1. <https://neon.com> → **Create project** (region close to Render, e.g. Singapore).
2. **Connect** → turn **Connection pooling off** → copy the connection string.
3. Convert it: start with `postgresql+asyncpg://`, replace everything after `?` with `ssl=require`:

   ```
   postgresql+asyncpg://neondb_owner:PASSWORD@ep-xxxx.ap-southeast-1.aws.neon.tech/neondb?ssl=require
   ```

4. Create your admin from your PC (tables are created automatically):

   ```powershell
   cd backend
   $env:DATABASE_URL = "postgresql+asyncpg://…neon…/neondb?ssl=require"
   uv run netribeat create-admin --email you@example.org --first-name You --last-name Admin
   Remove-Item Env:DATABASE_URL
   ```

## 2 · Email — Brevo

1. <https://www.brevo.com> → **Senders** → add and verify your sender address
   (with your own domain, also set up SPF/DKIM).
2. **SMTP & API → SMTP** → note the login and generate an SMTP key.
3. Server `smtp-relay.brevo.com`, **port 2525** (Render's free tier blocks 25/465/587).

## 3 · Redis — Render Key Value

Render → **New → Key Value** → Free, same region → copy the **internal** URL (`redis://red-xxxx:6379`).

## 4 · Backend — Render

**New → Web Service** → your GitHub repo:

| Setting | Value |
|---|---|
| Language | Docker |
| Dockerfile Path | `infra/Dockerfile.backend` |
| Build Context | `.` |
| Health Check Path | `/api/v1/health` |

Environment variables:

```
PORT=8000
WEB_CONCURRENCY=1
ENVIRONMENT=production
API_DOCS_ENABLED=false
COOKIE_SECURE=true
DATABASE_URL=postgresql+asyncpg://…neon…?ssl=require
REDIS_URL=redis://red-xxxx:6379
JWT_SECRET=<secret 1>
OTP_PEPPER=<secret 2>
FRONTEND_BASE_URL=https://<your-site>.vercel.app
CORS_ORIGINS=https://<your-site>.vercel.app
EMAIL_BACKEND=smtp
EMAIL_FROM=NetriBeat <verified-sender@example.com>
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=2525
SMTP_USERNAME=<Brevo login>
SMTP_PASSWORD=<Brevo SMTP key>
HIBP_CHECK_ENABLED=true
```

`ENVIRONMENT=development` also works (the safety checks are then skipped). Full list:
[Configuration](configuration.md).

Check: `https://<service>.onrender.com/api/v1/health/ready` → `"database": "ok", "redis": "ok"`.

## 5 · Website — Vercel

1. `frontend/vercel.json` must point at your Render service:

   ```json
   { "source": "/api/:path*", "destination": "https://<service>.onrender.com/api/:path*" }
   ```

2. Vercel → **Add New → Project** → import the repo → **Root Directory `frontend`**, preset
   **Vite**, build `npm run build`, output `dist`.
3. Put the Vercel address in Render's `FRONTEND_BASE_URL` and `CORS_ORIGINS` — exactly, with
   `https://` and no trailing `/`.

## 6 · Keep it awake — UptimeRobot

New HTTP(s) monitor → `https://<service>.onrender.com/api/v1/health`, every 5 minutes. Use
`/health` (not `/health/ready`) so Neon can still sleep.

## Free-tier limits

| Limit | Effect |
|---|---|
| Render sleeps after 15 min idle | First visit is slow — UptimeRobot prevents it |
| Render: 512 MB, 0.1 CPU | Keep `WEB_CONCURRENCY=1` |
| Neon: 0.5 GB | Uploaded hex files and results live in the database; delete old sessions when full |
| Neon: 6-hour restore window | Back up regularly: `pg_dump -Fc "postgresql://…neon…?sslmode=require" > backup.dump` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `unexpected keyword argument 'sslmode'` | Use `?ssl=require` in `DATABASE_URL` |
| `prepared statement … does not exist` | You used Neon's pooled host (`-pooler`); turn pooling off |
| `Unsafe production settings: …` | Fix the listed variable, or use `ENVIRONMENT=development` |
| No emails, log shows `email_delivery_failed` | Port 2525, verified sender, Brevo → Transactional → Logs, spam folder |
| Logged out on every reload / "Origin not allowed" | `FRONTEND_BASE_URL` / `CORS_ORIGINS` don't exactly match the Vercel address |
| Every API call 404 on Vercel | `vercel.json` destination is wrong, or Root Directory isn't `frontend` |
| `redis: unavailable` | Wrong `REDIS_URL` or a different region |

## Self-hosting (one server)

`infra/docker-compose.prod.yml` runs everything on one Linux server — PostgreSQL, Redis, the
backend, the website and Caddy with automatic HTTPS:

```bash
cd infra
cp .env.production.example .env.production     # fill it in
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.production exec api \
  netribeat create-admin --email you@example.org --first-name You --last-name Admin
```

Point your domain's DNS at the server first; open ports 80 and 443 only.
