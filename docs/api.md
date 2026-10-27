# API reference

Base URL: `/api/v1`. Interactive docs (when enabled): `/api/docs`.

[← Back to README](../README.md)

---

## Conventions

| Topic | Rule |
|---|---|
| JSON | camelCase fields; unknown fields are rejected |
| Auth | `Authorization: Bearer <accessToken>`; the refresh token travels in the `nb_refresh` cookie |
| CSRF | Cookie endpoints (`/auth/login`, `/refresh`, `/logout`) need `X-Requested-With: NetriBeat` |
| Errors | Always `{"code": "…", "message": "…", "fields": {"field": "message"}}` |
| Visibility | A `user` sees only their own data; someone else's id returns **404** |

| Status | `code` examples |
|---|---|
| 400 | `validation_error` (with `fields`), `bad_request` |
| 401 | `unauthorized`, `invalid_credentials` |
| 403 | `forbidden`, `csrf_failed` |
| 404 | `not_found` |
| 409 | `conflict`, `not_ready` (session has no results yet) |
| 413 | `payload_too_large` |
| 429 | `too_many_attempts` |
| 503 | `service_unavailable` (Redis down) |

## Health

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{"status": "ok"}` — process is up |
| GET | `/health/ready` | `checks.database`, `checks.redis` — 503 if either is down |

## Authentication — public

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/auth/register` | `firstName, lastName, email, password, confirmPassword` | 202 |
| POST | `/auth/verify-email` | `email, code` | 200 user |
| POST | `/auth/resend-verification` | `email` | 202 |
| POST | `/auth/login` | `email, password, remember?, mode? ("user"\|"admin")` | 200 `{token, expiresAt, user}` + cookie |
| POST | `/auth/refresh` | — (cookie) | 200 `{token, expiresAt, user}` |
| POST | `/auth/logout` | — (cookie) | 204 |
| POST | `/auth/forgot-password` | `email` | 202 |
| POST | `/auth/verify-reset-otp` | `email, code` | 200 `{resetToken, expiresAt}` |
| POST | `/auth/reset-password` | `resetToken, password, confirmPassword` | 204 |

## Me — signed in

| Method | Path | Body / notes |
|---|---|---|
| GET | `/auth/me` | Current user |
| GET · PATCH | `/users/me` | `firstName, lastName, age, gender, heightCm, weightKg, hrRest` (all optional) |
| POST | `/users/me/password` | `currentPassword, newPassword, confirmPassword` → 204 |
| GET | `/users/me/sessions` | Signed-in devices |
| DELETE | `/users/me/sessions/{id}` | Sign one device out |
| POST | `/users/me/sessions/revoke-others` | Sign all other devices out |
| GET · PUT | `/users/me/hr-max` | `method: "age"\|"peak"\|"manual"`, `manualValue` (100–230) → re-analyses my sessions |

## Sessions — signed in

| Method | Path | Notes |
|---|---|---|
| GET | `/sessions` | Query: `q`, `userId` (admin), `status`, `limit` (≤ 200), `offset` → `{items, total, stats}` |
| POST | `/sessions` | `multipart/form-data`, see below → 201 `{items: [session…]}` |
| GET | `/sessions/{id}` | Session details |
| GET | `/sessions/{id}/analysis` | `{sessionId, metrics}` |
| GET | `/sessions/{id}/signals` | `{sessionId, signals}` |
| POST | `/sessions/{id}/advanced` | Re-run Kubios-style HRV (body below) → `{metrics, series}` |
| POST | `/sessions/{id}/retry` | Analyse again from the stored file |
| DELETE | `/sessions/{id}` | 204 |
| GET | `/sessions/{id}/report` | PDF |
| GET | `/sessions/{id}/export.json` | JSON |
| GET | `/sessions/{id}/export.csv?dataset=metrics\|hr\|rr\|rms` | CSV |
| GET | `/sessions/{id}/files/{fileId}` | Original hex file (`fileId` is in `files[0].id`) |

**Upload form fields**

| Field | Type | Required |
|---|---|---|
| `files` | one or more hex files (≤ 10, ≤ 20 MB each) | yes |
| `type` | `training` · `rest` · `match` · `recovery` · `test` | no (training) |
| `device` | text | no |
| `recordedAt` | ISO date-time | no (from the file name, else now) |
| `age` | 8–100 | no |
| `gender` | `male` · `female` · `other` | no |
| `restingHr` | 25–120 | no |
| `heightCm` | 80–250 | no |
| `weightKg` | 20–300 | no |
| `hrMaxManual` | 100–230 | no |
| `notes` | ≤ 500 chars | no |
| `userId` | uuid — upload for another user | admins only |

A file that can't be decoded is rejected with `400` and `fields["files.N"]`.

**Advanced HRV body** (all optional): `sampleStartS`, `sampleLengthS` (≥ 30),
`correction` (`none`, `spec`, `very_low`, `low`, `medium`, `strong`, `very_strong`),
`detrend` (`none`, `smoothness_priors`), `smoothnessLambda`, `welchWindowS`, `arOrder`,
`tvWindowS`, `tvStepS`.

## Admin

| Method | Path | Body / notes |
|---|---|---|
| GET | `/admin/users` | Query: `q`, `role`, `isActive`, `sort`, `limit`, `offset` |
| POST | `/admin/users` | `email, firstName, lastName, age?, sendInvite?` |
| GET | `/admin/users/{id}` | |
| PATCH | `/admin/users/{id}/status` | `isActive` |
| PATCH | `/admin/users/{id}/role` | `role` |
| POST | `/admin/users/{id}/sessions/revoke-all` | |
| GET · PUT | `/admin/users/{id}/hr-max` | Same as `/users/me/hr-max` |
| GET | `/admin/audit-events` | Query: `action`, `targetUserId`, `limit`, `offset` |
