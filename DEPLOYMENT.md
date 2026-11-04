# LakeWatch — Deployment Guide

This is a **monorepo**: `backend/` (FastAPI + SQLAlchemy + Alembic) and
`frontend/` (React + Vite) live in one Git repository and are deployed
together. Two supported paths:

| Path | Use when | Time to first admin login |
| --- | --- | --- |
| **Docker Compose** (recommended) | you have Docker 24+ and docker compose v2 | ~5 minutes |
| **Manual** (venv + build + reverse proxy) | bare server / no Docker | ~20 minutes |

---

## 1. Docker Compose (recommended)

### 1.1 Configure

```bash
cp .env.example .env
```

Edit `.env`:

```ini
POSTGRES_USER=lakewatch
POSTGRES_PASSWORD=<strong password>
POSTGRES_DB=lakewatch

# REQUIRED — the backend refuses to start without a real secret:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
SECRET_KEY=<generated value>
ENVIRONMENT=production

# Optional: auto-create the first admin on health (or bootstrap manually later)
BOOTSTRAP_ADMIN_EMAIL=admin@example.org
BOOTSTRAP_ADMIN_PASSWORD=<min 10 chars>
BOOTSTRAP_ADMIN_NAME=System Administrator

JOBS_WORKER_COUNT=2

# Optional assistant. Leave blank to disable it.
# AI_BASE_URL=https://api.openai.com/v1
# AI_MODEL=<provider model name>
# AI_API_KEY=<server-side secret>
```

The dashboard assistant uses an OpenAI-compatible chat-completions API. The
backend keeps the provider key server-side. On an explicit user question, it
sends the question and displayed summary metrics only; raw imagery and
unpublished map layers are not sent. Leave the settings blank to disable the
assistant. For a local Ollama service, use
`AI_BASE_URL=http://host.docker.internal:11434/v1` in Docker Compose.

The Lake Malawi time-lapse is enabled by dated `water_extent` polygons from
computed satellite scenes whose source datasets have been published. It does
not fabricate shoreline changes when those polygons are absent.

### 1.2 Start

```bash
docker compose up --build -d
```

This brings up three services (see `docker-compose.yml`):

- **db** — `postgis/postgis:16-3.4` with a healthcheck; data persists in the
  `pgdata` volume.
- **backend** — FastAPI; the container entrypoint runs
  `alembic upgrade head` (schema migrations own the DB in production —
  `AUTO_CREATE_TABLES=false`) and then `uvicorn`. **All background work
  (ingest, processing, indicator evaluation, report builds) runs in-process
  workers** started by the app itself.
- **frontend** — multi-stage build: Vite `npm run build`, then **nginx** which
  serves the static app on port **8080** and proxies `/api/*` and `/docs`
  to the backend (see `frontend/nginx.conf`).

### 1.3 Create the first administrator

If you did not set `BOOTSTRAP_ADMIN_*`:

```bash
docker compose exec backend python -m app.cli bootstrap-admin \
  --email admin@example.org --name "System Administrator"
        # you will be prompted for a password (min 10 chars)
```

Then open **http://localhost:8080** and sign in. Public dashboard:
`http://localhost:8080/public` (no login).

### 1.4 Upgrade / operate

```bash
docker compose pull && docker compose up --build -d   # upgrades run alembic on boot
docker compose logs -f backend                        # follow API + worker logs
docker compose exec db pg_dump -U lakewatch lakewatch > backup.sql
docker compose down                                   # keeps pgdata + storage volumes
docker compose down -v                                # ⚠ also wipes the database
```

Persisted state lives in two named volumes: `pgdata` (database) and
`storage` (raw retrievals, processed products, exports, reports). Back up both
(`docker run --rm -v lakewatch_storage:/data -v $PWD:/bak alpine tar czf /bak/storage.tgz /data`).

---

## 2. Manual deployment (no Docker)

### 2.1 Database (production target)

PostgreSQL 14+ with **PostGIS 3**:

```sql
CREATE DATABASE lakewatch;
CREATE USER lakewatch WITH PASSWORD '...';
GRANT ALL PRIVILEGES ON DATABASE lakewatch TO lakewatch;
\c lakewatch
CREATE EXTENSION IF NOT EXISTS postgis;
```

### 2.2 Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -e .[dev]      # Windows; on Linux: .venv/bin/pip
                                         # plain `pip install -e .` is enough in production
```

`backend/.env` (full reference in `backend/.env.example`):

```ini
DATABASE_URL=postgresql+psycopg://lakewatch:...@localhost:5432/lakewatch
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(48))">
ENVIRONMENT=production
AUTO_CREATE_TABLES=false        # alembic owns the schema
STORAGE_ROOT=/srv/lakewatch/storage
CORS_ORIGINS=https://your-frontend-domain
```

Schema + first admin:

```bash
python -m alembic upgrade head
python -m app.cli bootstrap-admin --email admin@example.org --name "System Administrator"
```

Run as a service (option A — **systemd**, `backend/lakewatch-api.service`):

```ini
[Unit]
Description=LakeWatch API
After=network.target postgresql.service

[Service]
User=lakewatch
WorkingDirectory=/srv/lakewatch/backend
Environment=PATH=/srv/lakewatch/backend/.venv/bin
ExecStart=/srv/lakewatch/backend/.venv/bin/uvicorn app.main:app \
  --host 127.0.0.1 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```

`systemctl enable --now lakewatch-api`. Requirement note: the app starts its
own in-process background workers (jobs poll loop); no separate queue daemon
is needed for a single-node deployment.

### 2.3 Frontend

```bash
cd frontend
npm ci
VITE_API_BASE_URL=/api/v1 npm run build     # or bake the URL via vite config
```

Serve `frontend/dist/` **plus** proxy `/api` to the backend. Either nginx,
Caddy or a Node Static file server will do; the reference production config
is `frontend/nginx.conf` (SPA history fallback + `/api` and `/docs` proxy).

Example `nginx` server block:

```nginx
server {
  listen 80;
  server_name your-lakewatch-host;

  root /srv/lakewatch/frontend/dist;
  index index.html;
  location / { try_files $uri $uri/ /index.html; }   # SPA routes incl. /public

  location /api/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
  location /docs { proxy_pass http://127.0.0.1:8000; }
}
```

Put TLS in front (certbot / your load balancer) and add
`X-Forwarded-Proto` handling if you terminate HTTPS there.

---

## 3. Production hardening checklist

- [ ] `SECRET_KEY` is a long random value stored in the secret manager of the platform (never committed; `.env` is git-ignored).
- [ ] `ENVIRONMENT=production` (disables debug noise; docs still available for staff convenience — restrict `/docs` at the proxy if undesired).
- [ ] `AUTO_CREATE_TABLES=false`; schema changes only through `alembic upgrade head` (migrations are reviewed in Git).
- [ ] Postgres password not the compose default; DB port **not** exposed publicly (remove `5432:5432` from compose for production).
- [ ] `CORS_ORIGINS` set to the exact origins serving the app.
- [ ] File uploads/storage volume backed by persistent storage (bind mount or cloud block volume); backup `pgdata` **and** `storage`.
- [ ] First admin created via `bootstrap-admin` and the throwaway password rotated; researchers never get `public.publish` (see README §6.1).
- [ ] TLS everywhere; logout rotates tokens; audit log reviewed periodically (`/admin/audit`).
- [ ] Public dashboard monitored: it serves anonymous traffic — consider a CDN/rate-limit in front of `GET /api/v1/public/*`.

## 4. Smoke test after every deploy

```bash
curl -f http://HOST/health
curl -f http://HOST/api/v1/public/overview        # anonymous; total may be 0 — that's correct
curl -f http://HOST/api/v1/public/map
```

And in the UI: sign in as admin → publish one dataset and one alert from
their detail pages → open `/public` in a private window (not signed in) →
confirm the items appear and `study_area.name` stays hidden until the area
itself is published.
