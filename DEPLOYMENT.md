# LakeWatch — Deployment Guide

This is a **monorepo**: `backend/` (FastAPI + SQLAlchemy + Alembic) and
`frontend/` (React + Vite) live in one Git repository. Three supported paths:

| Path | Use when | Time to first admin login |
| --- | --- | --- |
| **Docker Compose** (recommended for a single host) | you have Docker 24+ and docker compose v2 | ~5 minutes |
| **Manual** (venv + build + reverse proxy) | bare server / no Docker | ~20 minutes |
| **Split hosting** (Cloudflare Pages + Render/Railway) | separate managed platforms for each app | ~15 minutes |

Sections 1–2 deploy both apps together on one origin, so no CORS is involved.
Section 5 covers the split deployment, where the frontend and backend have
different origins and the backend must allow the frontend's origin.

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

---

## 5. Split deployment: Cloudflare Pages (frontend) + Render/Railway (backend)

The monorepo stays one repository; each platform builds only the directory it
needs. This is the same code as the single-host setup, with three differences:
a **build-time API URL**, **CORS**, and **persistent storage**.

### 5.1 How the split is wired

| Concern | Where it is configured |
| --- | --- |
| Frontend build | Cloudflare Pages, **root directory `frontend`** |
| API URL baked into the bundle | `VITE_API_BASE_URL` in the Pages environment |
| Backend image | `backend/Dockerfile`, built with the **repo root** as context |
| Database | Render Postgres / Railway Postgres |
| Allowed browser origin | `CORS_ORIGINS` on the backend |
| SPA deep links | `frontend/public/_redirects` (Vite copies it into `dist/`) |
| Platform port | `backend/Dockerfile` binds `${PORT:-8000}` |

Authentication uses a bearer token in `localStorage`, not cookies, so no
cross-site cookie or `SameSite` configuration is needed. The browser sends
`Authorization: Bearer ...`; FastAPI's CORS middleware allows that header for
origins listed in `CORS_ORIGINS`.

**Build-context rule:** `backend/Dockerfile` does `COPY backend/ ./`, so the
Docker build context must be the repository root. When a platform asks for a
"root directory", leave it at the repo root and point at the Dockerfile — do
not set it to `backend/`.

### 5.2 Backend on Render (Blueprint)

The repository ships `render.yaml` at the root.

1. Render Dashboard → **New → Blueprint** → select this repository.
2. Apply the blueprint. It creates `lakewatch-db` (Postgres) and the
   `lakewatch-api` web service.
3. Open the service → **Environment** → set `CORS_ORIGINS` to the exact Pages
   origin, for example `https://lakewatch.pages.dev`. Add a comma-separated
   list if you use a custom domain as well. No trailing slash.
4. Wait for `/health` to report healthy, then create the first administrator
   from the Render **Shell**:

   ```bash
   python -m app.cli bootstrap-admin --email admin@example.org --name "System Administrator"
   ```

5. Note the service URL (e.g. `https://lakewatch-api.onrender.com`). The API
   docs live there at `/docs`; the frontend no longer proxies them.

Free-plan caveats: the free Postgres instance expires after about 30 days, free
web services sleep after inactivity (the first request is slow), and the
filesystem is ephemeral — uploads and generated reports survive only until the
next deploy. For real use, upgrade the service, attach a Render disk mounted at
`/var/data`, and keep `STORAGE_ROOT=/var/data/storage` (already the blueprint
default).

### 5.3 Backend on Railway

The repository ships `railway.toml` at the root.

1. Railway → **New Project → Deploy from GitHub repo**.
2. Add a **PostgreSQL** database to the project. Railway injects
   `DATABASE_URL`; `backend/app/core/config.py` rewrites `postgresql://` to the
   psycopg 3 dialect automatically, so no manual editing is needed.
3. Confirm the service root is the **repository root** (the Dockerfile copies
   `backend/`), and that the config file `railway.toml` is detected.
4. Set these service variables:

   ```ini
   SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(48))">
   ENVIRONMENT=production
   AUTO_CREATE_TABLES=false
   STARTUP_BOOTSTRAP=false
   JOBS_ENABLED=true
   JOBS_WORKER_COUNT=2
   STORAGE_ROOT=/data/storage
   CORS_ORIGINS=https://<your-pages-project>.pages.dev
   ```

5. Add a **Volume** mounted at `/data` so storage survives deploys, then
   generate a public domain under **Settings → Networking**.
6. Create the first admin from the Railway shell:

   ```bash
   python -m app.cli bootstrap-admin --email admin@example.org --name "System Administrator"
   ```

`railway.toml` builds `backend/Dockerfile`, checks `/health`, and restarts on
failure. The container entrypoint runs `alembic upgrade head` before Uvicorn,
so migrations apply on every deploy.

### 5.4 Frontend on Cloudflare Pages

1. Cloudflare Dashboard → **Workers & Pages → Create → Pages → Connect to Git**.
2. Select the repository.
3. Framework preset: **Vite** (or `None`).
4. **Root directory:** `frontend`.
5. **Build command:** `npm ci && npm run build`.
6. **Build output directory:** `dist`.
7. Environment variables:
   - `VITE_API_BASE_URL=https://<backend-host>/api/v1` — absolute, with the
     `/api/v1` suffix and no trailing slash.
   - `NODE_VERSION=22`.
8. Deploy.

`frontend/public/_redirects` contains `/* /index.html 200`, so deep links such
as `/public`, `/research/analysis` and `/admin/users` work on refresh. Vite
copies that file into `dist/` during the build.

`VITE_API_BASE_URL` is **inlined at build time**. Changing the backend URL (for
example after renaming a Render service) requires a new frontend deployment.
Cloudflare preview deployments receive a random `*.pages.dev` hostname; either
add that hostname to `CORS_ORIGINS` and redeploy the backend, or restrict
preview deployments to the production branch.

### 5.5 Minimum backend variables for the split setup

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | injected by Render/Railway (both URL forms are accepted) |
| `SECRET_KEY` | long random value, generated by the platform or you |
| `ENVIRONMENT` | `production` |
| `AUTO_CREATE_TABLES` | `false` — Alembic owns the schema |
| `STARTUP_BOOTSTRAP` | `false` — create the admin explicitly |
| `STORAGE_ROOT` | Render `/var/data/storage`, Railway `/data/storage` |
| `JOBS_ENABLED` | `true` |
| `CORS_ORIGINS` | the exact Pages origin(s), comma-separated |
| `AI_*` | optional; leave blank to disable the assistant |

Keep the backend at **one instance**. Background jobs (ingestion, processing,
indicator runs, report builds) execute inside the API process; scaling to
multiple instances would run duplicate workers. If you need horizontal scaling
later, move the job runner into a separate worker service first.

### 5.6 Post-deploy verification

```bash
curl -f https://<backend-host>/health
curl -f https://<backend-host>/api/v1/public/overview   # anonymous; total may be 0
curl -f https://<backend-host>/api/v1/public/map
```

Then, in a browser:

1. Open the Pages URL, sign in, and confirm the dashboard loads data from the
   backend origin (browser DevTools → Network shows requests to the Render or
   Railway host, not the Pages host).
2. Publish one dataset and one alert, open `/public` in a private window, and
   confirm the published items appear.
3. If the browser reports a CORS error, compare the `Origin` request header
   byte-for-byte with `CORS_ORIGINS` (scheme + host, no trailing slash) and
   redeploy the backend after changing it.

### 5.7 Optional: remove CORS entirely with a same-origin proxy

If you would rather keep the browser talking to one origin, add a Cloudflare
Pages Function that forwards `/api/*` to the backend and build the frontend
with the default `VITE_API_BASE_URL=/api/v1`. Create
`frontend/functions/api/[[path]].ts`:

```ts
export const onRequest: PagesFunction<{ API_ORIGIN: string }> = async ({ request, env, params }) => {
  const rest = Array.isArray(params.path) ? params.path.join("/") : (params.path ?? "");
  const incoming = new URL(request.url);
  const target = new URL(`/api/${rest}${incoming.search}`, env.API_ORIGIN);
  return fetch(new Request(target, request));
};
```

Set `API_ORIGIN=https://<backend-host>` as a Pages variable and leave
`VITE_API_BASE_URL` unset (it then defaults to `/api/v1`). The browser sees only
the Pages origin, so `CORS_ORIGINS` is no longer involved. The direct-URL
approach in §5.4 is simpler; use the proxy when you want a single public origin
or a place to add edge caching/rate limiting.
