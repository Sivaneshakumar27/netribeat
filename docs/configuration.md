# Configuration

The backend reads every setting from environment variables, or from `backend/.env` locally.
Template: `backend/.env.example`. Source of truth: `backend/src/netribeat/config.py`.

[← Back to README](../README.md)

---

## Required

| Variable | Example | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:5432/db` | Neon: end with `?ssl=require` (not `sslmode`) |
| `JWT_SECRET` | 48 random characters | Signs access tokens. ≥ 32 chars |
| `OTP_PEPPER` | 48 *different* random characters | Key for code / token hashes. ≥ 32 chars, ≠ `JWT_SECRET` |

Generate a secret: `uv run python -c "import secrets; print(secrets.token_urlsafe(48))"`

## Environment and browser

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `production` turns on the safety checks below and hides `/api/docs` |
| `REDIS_URL` | `redis://localhost:6379/0` | Rate-limit counters |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | Exact site address (https in production) |
| `CORS_ORIGINS` | *(empty)* | Comma-separated; must include the site address. Never `*` |
| `COOKIE_SECURE` | `true` | `false` only for local http |
| `COOKIE_DOMAIN` | *(none)* | Leave empty |
| `API_DOCS_ENABLED` | on except production | Forces `/api/docs` on or off |
| `TRUST_PROXY_HEADERS` | `false` | |
| `LOG_LEVEL` | `INFO` | |

## Email

| Variable | Default | Notes |
|---|---|---|
| `EMAIL_BACKEND` | `console` | `console` · `file` · `smtp` (production requires `smtp`) |
| `EMAIL_FROM` | `NetriBeat <no-reply@localhost>` | A sender verified at your provider |
| `EMAIL_FILE_DIR` | `./var/mail` | For `file` |
| `SMTP_HOST` / `SMTP_PORT` | — / `587` | Brevo on Render: `smtp-relay.brevo.com` / `2525` |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | — | |
| `SMTP_STARTTLS` / `SMTP_SSL` | `true` / `false` | `SMTP_SSL=true` for port 465 |
| `SMTP_TIMEOUT_SECONDS` | `15` | |

## Sign-in and passwords

| Variable | Default | |
|---|---|---|
| `ACCESS_TOKEN_MINUTES` | `15` | 1–60 |
| `SESSION_HOURS_DEFAULT` | `12` | Without *Keep me signed in* |
| `SESSION_DAYS_REMEMBER` | `30` | With *Keep me signed in* |
| `PASSWORD_MIN_LENGTH` / `PASSWORD_MAX_LENGTH` | `12` / `128` | Minimum never below 8 |
| `HIBP_CHECK_ENABLED` | `false` | Breached-password check (needs outbound HTTPS) |

## Codes and rate limits

| Variable | Default | |
|---|---|---|
| `OTP_LENGTH` · `OTP_TTL_MINUTES` · `OTP_MAX_ATTEMPTS` | `6` · `10` · `5` | Email codes |
| `OTP_RESEND_COOLDOWN_SECONDS` · `OTP_MAX_SENDS_PER_HOUR` | `60` · `3` | Per address |
| `RESET_TOKEN_TTL_MINUTES` | `10` | |
| `PENDING_REGISTRATION_HOURS` | `24` | Unverified sign-ups are deleted after this |
| `LOGIN_FAIL_LIMIT_PER_EMAIL` · `_PER_IP` · `LOGIN_WINDOW_MINUTES` | `10` · `30` · `15` | |
| `FORGOT_LIMIT_PER_IP_PER_HOUR` · `REGISTER_LIMIT_PER_IP_PER_HOUR` | `10` · `10` | |
| `OTP_VERIFY_LIMIT_PER_IP` · `OTP_VERIFY_WINDOW_MINUTES` | `30` · `15` | |
| `MAX_JSON_BODY_BYTES` | `65536` | Upload limits are fixed: 10 files × 20 MB |

## Production safety checks

With `ENVIRONMENT=production` the backend refuses to start unless:

- `COOKIE_SECURE=true`
- `EMAIL_BACKEND=smtp` (and `SMTP_HOST` is set)
- `CORS_ORIGINS` is set and has no `*`
- `FRONTEND_BASE_URL` starts with `https://`

Secrets are always checked: ≥ 32 characters and different from each other.

## Frontend

The frontend has no environment variables. `frontend/vercel.json` forwards `/api/*` to the backend;
locally `vite.config.js` forwards to `http://127.0.0.1:8000` (override with `NETRIBEAT_API`).
