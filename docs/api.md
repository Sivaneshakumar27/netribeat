# API

The machine-readable contract is [`openapi.json`](openapi.json). A test fails if it ever
differs from the running app. Interactive docs: `http://localhost:8000/api/docs` (off in production unless `API_DOCS_ENABLED=true`).

All errors use one schema: `{"code": "...", "message": "...", "fields": {"camelCaseField": "message"}}`.
Request validation errors are **400** `validation_error` (FastAPI's default 422 is
remapped, per CLAUDE.md).

## Endpoints

| Method & path | Auth | Purpose | Success |
|---|---|---|---|
| POST `/api/v1/auth/register` | public | Start sign-up; emails a 6-digit code | 202 (same answer whether or not the email exists) |
| POST `/api/v1/auth/verify-email` | public | Code → active `user` account | 200 `User` |
| POST `/api/v1/auth/resend-verification` | public | New code (60 s cooldown, 3 per hour, silent) | 202 |
| POST `/api/v1/auth/login` | public | `{email, password, remember, mode: user\|admin}` → access token + refresh cookie | 200 |
| POST `/api/v1/auth/refresh` | refresh cookie + `X-Requested-With: NetriBeat` | Rotate cookie, new access token | 200 |
| POST `/api/v1/auth/logout` | cookie and/or bearer + CSRF header | Revoke this device | 204 |
| GET `/api/v1/auth/me` | bearer | Current user | 200 |
| POST `/api/v1/auth/forgot-password` | public | Email a reset code (same answer for any email) | 202 |
| POST `/api/v1/auth/verify-reset-otp` | public | Code → single-use `resetToken` (10 min) | 200 |
| POST `/api/v1/auth/reset-password` | reset token | New password; signs out every device | 204 |
| GET/PATCH `/api/v1/users/me` | bearer | Profile: name, age, and optional `sex`, `heightCm` (80–250), `weightKg` (20–300), `hrRest` (25–120) for the report header | 200 |
| POST `/api/v1/users/me/password` | bearer | Change password; signs out other devices | 204 |
| GET `/api/v1/users/me/sessions` | bearer | My signed-in devices (no tokens; `current` marks this one) | 200 |
| DELETE `/api/v1/users/me/sessions/{id}` | bearer | Sign out one of my devices (another user's id → 404) | 204 |
| POST `/api/v1/users/me/sessions/revoke-others` | bearer | Sign out every device except this one | 204 |
| GET/POST `/api/v1/admin/users` | admin | List/search/filter/sort/paginate; create user (no password, invite email) | 200 / 201 |
| GET `/api/v1/admin/users/{id}` | admin | One user | 200 |
| PATCH `/api/v1/admin/users/{id}/status` | admin | Enable or disable; signs the user out | 200 |
| PATCH `/api/v1/admin/users/{id}/role` | admin | Change role; signs the user out | 200 |
| POST `/api/v1/admin/users/{id}/sessions/revoke-all` | admin | Sign a user out of every device | 204 |
| GET `/api/v1/admin/audit-events` | admin | Audit log | 200 |
| GET `/api/v1/sessions` | bearer | List sessions (own; admins: all, `userId` filter). `q`, `status`, `limit`, `offset`; `stats` cover the whole filter | 200 |
| POST `/api/v1/sessions` | bearer | Multipart upload: `files` (1–10 × .json/.csv/.txt, ≤ 50 MB each; ECG or RR formats, see the README), optional `type`, `device`, `recordedAt` (ISO 8601 with offset), `age`, `hrMaxManual`, `notes`, `userId` (admins only). One session per file | 202 |
| GET `/api/v1/sessions/{id}` | bearer, owner or admin | Details, status, error, files | 200 |
| GET `/api/v1/sessions/{id}/analysis` | bearer, owner or admin | Stored metrics, warnings, unavailable reasons, provisional rules | 200 / 409 not ready |
| GET `/api/v1/sessions/{id}/signals` | bearer, owner or admin | 1 Hz HR, RR raw/corrected, artefact indices, 10 s ECG strip, per-minute series | 200 / 409 |
| GET `/api/v1/sessions/{id}/report` | bearer, owner or admin | PDF report | 200 |
| GET `/api/v1/sessions/{id}/export.json` | bearer, owner or admin | Metrics + signals + provenance | 200 |
| GET `/api/v1/sessions/{id}/export.csv?dataset=metrics\|hr\|rr\|psd` | bearer, owner or admin | CSV export | 200 |
| GET `/api/v1/sessions/{id}/files/{fileId}` | bearer, owner or admin | Original uploaded file | 200 |
| POST `/api/v1/sessions/{id}/advanced` | bearer, owner or admin | Re-run the advanced HRV analysis: `sampleStartS`, `sampleLengthS` (null = to end), `correction` (none / spec / very_low … very_strong), `detrend`, `smoothnessLambda`, `welchWindowS`, `arOrder`, `tvWindowS`, `tvStepS`. Persisted | 200 / 400 / 409 |
| DELETE `/api/v1/sessions/{id}` | bearer, owner or admin | Delete the session, results and stored file | 204 |
| POST `/api/v1/sessions/{id}/retry` | bearer, owner or admin | Re-run a failed analysis | 200 / 409 |
| GET/PUT `/api/v1/users/me/hr-max` | bearer | Max HR method (`age`/`peak`/`manual`, 100–230); PUT recomputes zones and load for your sessions | 200 |
| GET/PUT `/api/v1/admin/users/{id}/hr-max` | admin | The same, for any user | 200 |
| GET `/api/v1/health`, `/api/v1/health/ready` | public | Liveness / readiness (database, Redis) | 200 / 503 |

## Compatibility with the supplied `docs-original/api-spec.yaml`

Intentional changes, all required by the master prompt:

1. **Terminology:** "athlete" is now "user" everywhere. A contract test fails if "athlete"
   appears in the API.
2. **Public registration exists.** The original CLAUDE.md said there was no sign-up
   screen; the new requirements override that.
3. **Login:** adds `remember` and `mode`. The response (`token`, `expiresAt`, `user`)
   matches the original `LoginResponse`. The access token now lasts 15 minutes;
   "remember me" controls the refresh session instead (12 h default, 30 days with
   remember), keeping the AUTH-2 lifetimes.
4. **Password reset:** AUTH-5's emailed link token is replaced by OTP →
   `verify-reset-otp` → `resetToken` → `reset-password {resetToken, password,
   confirmPassword}`. `forgot-password` answers **202** (the original said 204).
5. **New endpoints:** `verify-email`, `resend-verification`, `refresh`,
   `verify-reset-otp`, `/users/me*`, `/admin/*`.
6. **`User` schema** extends BE-0.2 with `firstName`, `lastName`, `emailVerified`,
   `hasPassword`, `isActive`, `createdAt`, `lastLoginAt`.

7. **Sessions:** paths and response fields follow the original spec, with "athlete" →
   "user": `email` becomes `userEmail`, plus `userId` and `userName`. Deliberate
   differences:
   - Each uploaded file becomes **its own session** (the dataset rules say each file is a
     separate recording), so the upload returns `{items: [...]}`.
   - `age`, `recordedAt` and `type` are **optional**: age and recording time are read
     from CSV headers when present.
   - The file kind is detected from the **content**, not the name.
   - `Session` adds `reliable`, `ageSource`, `recordedAtSource`, `attempts` and `error`.
   - `Analysis` adds `quality`, `reliability`, `warnings`, `unavailable`,
     `provisionalRules` and `analysisVersion`.
   - Unavailable metrics are `null`, with a reason in `unavailable`.
   - New endpoints: `export.csv`, `export.json`, `files/{fileId}`, `DELETE`, `retry`.
8. **`/athletes/{email}/hr-max`** becomes `/users/me/hr-max` (self) and
   `/admin/users/{id}/hr-max` (admins). Ids are used instead of emails in paths.
