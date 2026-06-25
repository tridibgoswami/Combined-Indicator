# Deployment

## Local engine-only mode (unchanged)

```
pip install -r requirements.txt
cp .env.example .env   # fill in AngelOne creds; keep PAPER_TRADE=true
python main.py
```

This runs exactly as before the platform changes — no Docker, DB, or Redis
required.

## Full platform mode (Docker Compose)

```
cp .env.example .env   # fill in AngelOne creds + ADMIN_EMAIL/ADMIN_PASSWORD + JWT_SECRET
docker compose -f deployment/docker-compose.yml up -d
```

Services started:
- `postgres` — platform database
- `redis` — engine state cache / emergency-stop flag / rate-limit locks
- `trading-engine` — runs `python main.py` in `engine.mode: live` per
  `config/config.yaml`
- `backend-api` — FastAPI control plane on port 8000
- `dashboard` — Next.js PWA on port 3000
- `nginx` — reverse proxy on port 80 (`/` -> dashboard, `/api/` -> backend)

First login: the backend bootstraps one admin user from `ADMIN_EMAIL` /
`ADMIN_PASSWORD` the first time it starts with an empty `users` table. Change
the password immediately after first login (no password-change endpoint
exists yet — rotate by re-running the bootstrap against a fresh DB, or add
one before going live).

## VPS setup

1. `git clone` the repo to `/opt/trading-platform` on the VPS.
2. Create `.env` from `.env.example` (never commit it).
3. Either:
   - Run `docker compose -f deployment/docker-compose.yml up -d`, or
   - Use the systemd units in `deployment/systemd/` for a non-Docker setup
     (copy them to `/etc/systemd/system/`, `systemctl daemon-reload`,
     `systemctl enable --now trading-engine backend-api`).
4. Put `deployment/nginx.conf` behind a real TLS termination (certbot/Let's
   Encrypt) so the dashboard and API are served over HTTPS, not bare HTTP.
5. Optionally add an IP allowlist in `nginx.conf` (commented block already
   there) if the dashboard should only be reachable from known networks.

## GitHub Actions deploy

`.github/workflows/ci.yml` runs lint+test on every push, builds both Docker
images on `main`, then SSHes into the VPS and runs
`docker compose -f deployment/docker-compose.yml up -d --build`. Required
repository secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`. Configure these
under Settings -> Secrets -> Actions, and gate the `deploy` job behind a
GitHub Environment with required reviewers if you want a manual approval
step before every production deploy.

## Config vs secrets

- `config/config.yaml` — everything non-secret: strategy params, execution
  mode, risk settings, expiry rules. Edit directly or via
  `PATCH /config {"path": "...", "value": ...}`.
- `.env` — secrets only (broker creds, JWT secret, DB/Redis URLs, admin
  bootstrap password). Never committed; `.env.example` documents the shape.
- `config/instruments.yaml` — non-secret per-underlying expiry rules
  (BankNifty monthly, Nifty weekly Tuesday) and scrip-master cache settings.
