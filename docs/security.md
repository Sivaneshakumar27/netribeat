# Security model

## What is protected, and how

| Threat | Control | Tested |
|---|---|---|
| Password theft from the database | Argon2id (argon2-cffi defaults: t=3, 64 MiB, p=4); transparent rehash on login | yes |
| Weak passwords | Configurable minimum length (default 12, floor 8), common-password blocklist, no email or name in the password, optional HIBP k-anonymity check | yes |
| Account enumeration | Register, resend and forgot-password give identical responses; every login failure is the same 401; Argon2 runs on every path | yes |
| Self-promotion to admin | `role` accepts only `"user"`; unknown fields rejected; admins only via CLI, or by an existing admin on a separate endpoint | yes |
| OTP brute force | 6 digits; 5 attempts per code, then the code is closed; codes expire after 10 min; 30 checks per IP per 15 min; 60 s resend cooldown; 3 emails per address per hour | yes |
| OTP or token leak from the database | Only HMAC-SHA256 hashes stored (server pepper, bound to purpose and email) | yes |
| Reset-token misuse | Separate token issued only after a correct OTP; single use; 10 min; signs out every device | yes |
| Stolen access token | 15 min lifetime; checked against the session row on every request, so logout and disable take effect immediately; role read from the database, never from the token | yes |
| Stolen refresh token | HttpOnly, Secure (in production), SameSite=Strict, path `/api/v1/auth`; rotated on every use; reuse of an old token revokes the session (20 s grace for two tabs) | yes |
| CSRF | SameSite=Strict, plus a required `X-Requested-With` header (forces a CORS preflight), plus an Origin allow-list on cookie endpoints | yes |
| XSS stealing tokens | The access token is kept in memory only; the refresh token isn't readable by JavaScript; strict CSP on API responses | partly — see limits |
| Credential stuffing | 10 failures per email and 30 per IP in 15 min, counted in Redis; fails closed (503) if Redis is down | yes |
| Races (double sign-up or verification) | `ON CONFLICT` upsert, row locks (`FOR UPDATE`), advisory lock per challenge, unique indexes | yes, with real concurrent requests |
| SQL injection | ORM / bound parameters only; LIKE wildcards escaped in search | yes |
| Secrets in logs | Key=value logs without query strings; a redaction filter; a test runs the whole lifecycle and searches logs and every table for passwords, codes and tokens | yes |
| Unsafe production configuration | Startup refuses: short or equal secrets, `COOKIE_SECURE=false`, a non-SMTP mailer, `*` CORS, a non-HTTPS frontend URL | yes |
| Oversized requests | 64 KB JSON body limit (413) | yes |
| Lost or stolen device | Users list their devices and sign any of them out; admins can sign a user out everywhere; another user's session id returns 404 | yes |
| Spoofed client IP | In production Caddy discards client `X-Forwarded-For`; only Caddy can reach the API | yes (over HTTPS) |
| Downgrade / clickjacking / content injection | HTTPS-only with HSTS (2 years), HTTP→HTTPS redirect, frontend CSP `script-src 'self'` with no inline scripts, `frame-ancestors 'none'` | yes (over HTTPS) |
| API reconnaissance | Interactive API docs off in production | yes |
| Reading another user's recordings | Every session query is scoped to the actor in the service layer; another user's id returns 404 on every endpoint (details, analysis, signals, report, exports, original file, delete, retry); a `userId` filter can't widen a user's scope; only admins may upload for another user | yes |
| Malicious uploads | Size limits at Caddy (512 MB per request) and in the API (50 MB per file, 10 files); the content is checked before storing; files are never executed; they are stored under random 128-bit names (the original name is display text only); storage keys are validated against path traversal; the parsers handle arbitrary bytes without crashing (fuzz-tested) | yes |
| Leaking internals from failed analyses | Users see a safe message; stack traces are logged server-side with the session id only | yes |
| Known-vulnerable dependencies | `make audit` (pip-audit); Starlette and pytest minimum versions set after findings | run at packaging |

## Known limits (honest list)

- **XSS:** an XSS bug in the frontend could still call the API while the page is open.
  This is mitigated by the strict CSP, React's escaping, and having no
  `dangerouslySetInnerHTML` and no third-party scripts.
- **Behind an additional proxy or CDN** (e.g. Cloudflare in front of Caddy), configure
  Caddy's `trusted_proxies` for that CDN. Otherwise every user appears to come from the
  CDN's IPs and shares its rate limits.
- **Email change** isn't supported yet (it needs re-verification).
- **No TOTP or WebAuthn second factor** for admins yet. Recommended before production.
- **Audit log retention:** events are kept indefinitely for now; a retention policy is still to be decided.
- **Not verified:** the Docker images and Compose files weren't built (no Docker where this was prepared), and the Windows steps weren't run on Windows.
