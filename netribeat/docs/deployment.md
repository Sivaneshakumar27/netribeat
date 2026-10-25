# Deploying NetriBeat on a real domain (HTTPS)

Result: `https://your-domain` serves NetriBeat (accounts, recording upload, analysis
dashboards and reports) to anyone on the internet. Certificates come from Let's Encrypt and renew automatically. Real emails go
out through your SMTP provider.

```
Internet ──443/80──▶ Caddy (web container: HTTPS, React app, /api proxy)
                          │ private Docker network
                          ├──▶ FastAPI (api container, 2 workers, migrations on start)
                          ├──▶ Arq worker (analysis jobs; shares the storage volume)
                          ├──▶ PostgreSQL 16 (no public port, persistent volume)
                          └──▶ Redis 7 (no public port, password protected)
```

## What you need

1. **A Linux server** with a public IP: Ubuntu 24.04, 1 vCPU and 2 GB RAM is enough to
   start. Any provider works (Hetzner, DigitalOcean, AWS Lightsail, Azure, OVH, …).
2. **A domain or subdomain**, e.g. `app.example.org`. In your DNS provider, create an
   **A record** pointing `app` to the server's IP. Wait until
   `Resolve-DnsName app.example.org` in PowerShell shows that IP.
3. **An SMTP account** (see "Email" below).
4. On your Windows PC: PowerShell. `ssh` and `scp` are built into Windows 10/11.

## Step 1: prepare the server (run once)

From **PowerShell on your PC**:

```powershell
ssh root@YOUR_SERVER_IP
```

You are now **on the server** (a Linux shell). Run:

```bash
apt-get update && apt-get -y upgrade
curl -fsSL https://get.docker.com | sh            # installs Docker Engine + Compose plugin
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw allow 443/udp && ufw --force enable
mkdir -p /opt/netribeat && exit
```

## Step 2: upload the project

From **PowerShell on your PC**, in the folder that contains the zip:

```powershell
scp .\netribeat-auth.zip root@YOUR_SERVER_IP:/opt/netribeat/
ssh root@YOUR_SERVER_IP
```

On the server:

```bash
apt-get install -y unzip
cd /opt/netribeat && unzip -o netribeat-auth.zip && cd netribeat/infra
cp .env.production.example .env.production
chmod 600 .env.production
for i in 1 2 3 4; do openssl rand -base64 48 | tr -d '\n=+/' | cut -c1-48; done   # 4 secrets
nano .env.production
```

In `nano`, set `DOMAIN`, `ACME_EMAIL`, the four secrets (`POSTGRES_PASSWORD`,
`REDIS_PASSWORD`, `JWT_SECRET` and `OTP_PEPPER`, all different), and your SMTP details.
Save with `Ctrl+O`, `Enter`, then exit with `Ctrl+X`.

## Step 3: start it

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.production ps     # all "healthy"/"running"
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f web   # watch the certificate being issued; Ctrl+C to stop watching
```

The first build takes a few minutes. Database migrations run automatically every time
the API starts.

## Step 4: create the first administrator

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec api \
  netribeat create-admin --email you@example.org --first-name Your --last-name Name
```

You'll be asked for the password twice (12+ characters; it isn't shown). This is the
**only** way to create an administrator.

## Step 5: use it

- `https://YOUR_DOMAIN/register`: anyone can sign up and gets a real email with a code.
- `https://YOUR_DOMAIN/admin/login`: administrator sign-in. The dashboard has Users
  (search, create, enable/disable, roles, sign out everywhere) and Audit log.
- `https://YOUR_DOMAIN/upload`: upload Movesense `.json` / `.csv` recordings. They are
  analysed by the worker within seconds.
- `https://YOUR_DOMAIN/api/v1/health/ready` should show `"database":"ok","redis":"ok"`.
- `dc ps` (see below) should show the `worker` as running. Without it, uploads stay
  "processing". Jobs wait in Redis and run as soon as the worker starts, and on start
  the worker also picks up any session that was left half-done.

## Email (SMTP)

Production refuses to start without SMTP. Use any provider:

| Provider | SMTP_HOST | Port / mode | Username / password |
|---|---|---|---|
| Brevo | `smtp-relay.brevo.com` | 587 STARTTLS | your login / SMTP key |
| SendGrid | `smtp.sendgrid.net` | 587 STARTTLS | `apikey` / API key |
| Mailgun | `smtp.mailgun.org` | 587 STARTTLS | domain SMTP credentials |
| Amazon SES | `email-smtp.<region>.amazonaws.com` | 587 STARTTLS | SES SMTP credentials |
| Microsoft 365 | `smtp.office365.com` | 587 STARTTLS | mailbox / password (SMTP AUTH must be enabled) |
| Gmail / Google Workspace | `smtp.gmail.com` | 587 STARTTLS | address / **app password** (needs 2-step verification) |

For port 465, set `SMTP_PORT=465`, `SMTP_SSL=true`, `SMTP_STARTTLS=false`.

So that mail isn't marked as spam, verify your sending domain with the provider and add
the **SPF** and **DKIM** DNS records it gives you (and ideally DMARC). `EMAIL_FROM`
must use that domain.

If delivery fails, the request still succeeds: this is deliberate, so responses can't
reveal account existence. The failure is logged. Check it with
`docker compose ... logs api | grep email_delivery_failed`.

## Operating it

All commands run in `/opt/netribeat/netribeat/infra`. Define a shortcut first:

```bash
alias dc='docker compose -f docker-compose.prod.yml --env-file .env.production'
```

| Task | Command |
|---|---|
| Status | `dc ps` |
| Logs | `dc logs -f api` / `dc logs -f web` |
| Back up the database | `dc exec -T postgres pg_dump -U netribeat -Fc netribeat > /root/netribeat-$(date +%F).dump` |
| Daily automatic backup | `crontab -e`, then add: `15 3 * * * cd /opt/netribeat/netribeat/infra && docker compose -f docker-compose.prod.yml --env-file .env.production exec -T postgres pg_dump -U netribeat -Fc netribeat > /root/netribeat-$(date +\%F).dump && find /root -name 'netribeat-*.dump' -mtime +14 -delete` |
| Back up uploaded recordings | `docker run --rm -v netribeat_storage:/data -v /root:/backup alpine tar czf /backup/netribeat-files-$(date +%F).tgz -C /data .` |
| Worker logs / scale up | `dc logs -f worker` / `dc up -d --scale worker=2` |
| Copy backups off the server (PowerShell on your PC) | `scp root@YOUR_SERVER_IP:/root/netribeat-*.dump .` |
| Restore a backup | `dc stop api worker cleanup` → `cat FILE.dump \| dc exec -T postgres pg_restore -U netribeat -d netribeat --clean --if-exists` → `dc start api worker cleanup`; restore files with `docker run --rm -v netribeat_storage:/data -v /root:/backup alpine tar xzf /backup/FILE.tgz -C /data` |
| Update to a new version | upload and unzip the new zip (step 2, but keep `.env.production`), then `dc up -d --build`. Migrations apply automatically; data volumes are kept |
| Disable a compromised account | `dc exec api netribeat disable-user --email person@example.org` (signs them out everywhere) |
| Sign everyone out (e.g. after a leak) | change `JWT_SECRET` in `.env.production`, then `dc up -d` |
| Rotate the database password | `dc exec postgres psql -U netribeat -c "ALTER ROLE netribeat PASSWORD 'NEW'"`, update `POSTGRES_PASSWORD`, `dc up -d` |

**Never** run `dc down -v`: `-v` deletes the database and certificate volumes.

## Security notes for this deployment

- Uploads are capped at 512 MB per request by Caddy, and at 50 MB per file and 10 files
  by the API. Files are stored on the `storage` volume under random names.
- Only ports 22, 80 and 443 are open. PostgreSQL and Redis have no published ports.
- Caddy discards client-supplied `X-Forwarded-For`, so rate limits and the audit log
  see real client IPs. The API container can only be reached from Caddy.
- The API runs as an unprivileged user. API docs are off in production
  (`API_DOCS_ENABLED=true` turns them on).
- Use SSH keys and disable password login for SSH (`PasswordAuthentication no` in
  `/etc/ssh/sshd_config`).

## What was and wasn't verified

The exact Caddyfile, the API in `ENVIRONMENT=production` with `JOB_BACKEND=arq`, the
Arq worker as a separate process, migrations, CLI admin bootstrap, and real SMTP
delivery were run together over HTTPS. All 10 supplied recordings were uploaded and
analysed this way. Everything worked:
Secure cookies, HSTS/CSP, HTTP→HTTPS redirect, spoofed-IP rejection, admin actions, and
password reset by email. The **Docker images and `docker-compose.prod.yml` were not
built or run**, because Docker isn't available in the environment where this was
prepared. If `dc up --build` reports an error, the message points to the line; the
same configuration was verified outside containers.
