# LakeWatch — Satellite & ML Lake Malawi Monitoring

LakeWatch is a full-stack monitoring platform for **Lake Malawi** water level and
water quality. This repository implements five of the planned modules end to end:

1. **Admin Module** — user and role administration, data-source configuration,
   threshold configuration with versioning, and an append-only audit log.
2. **Data Analysis & Research Module** — satellite/climate data ingestion,
   geospatial preprocessing, indicator computation, quality flagging, a research
   workspace (time series, comparison), and exports.
3. **Disaster Management Module** — comparison of indicator/forecast values
   against approved thresholds, alerts with hazard type and severity, and a
   permanent record of every user response (acknowledge / note / resolve /
   reopen).
4. **Report Generation Module** — periodic and custom reports with a frozen
   build-time snapshot, stored in the file store and downloadable as PDF or
   CSV. The report draws on indicators (summary statistics), recorded
   forecast values and disaster alerts; the “statistics” it contains are
   computed at build time from stored data, not by a separate statistics
   module.
5. **Public Data Module** — an anonymous, read-only public dashboard
   (`/public`, no login) that shows maps, published datasets and published
   disaster alerts. Nothing is public by default: staff with `public.publish`
   explicitly publish datasets, study areas and alerts, every decision is
   audit-logged, and unpublishing takes effect immediately.
6. **LakeWatch dashboard** — a Malawi map with a Lake Malawi shoreline
   highlight, automatically refreshed published layers, recorded forecasts,
   water-extent history and a contextual AI explanation panel. The shoreline
   time-lapse appears only when dated water-extent polygons have been computed
   and their source datasets published.

> **Scope note.** Machine Learning, Report Generation, Public Data and
> Statistics modules are intentionally **not** part of this build. The platform
> does not generate forecasts; *projected* values can be recorded manually on
> the Disaster → Forecast values page (provenance note mandatory), and the
> alert engine compares them exactly like computed indicator values.

---

## 1. Architecture at a glance

| Layer      | Technology |
|------------|------------|
| Frontend   | React 18 + TypeScript, Vite 6, Tailwind CSS 3, React Router 6, TanStack Query 5, React Hook Form + Zod, Recharts 2, Leaflet / react-leaflet |
| Backend    | Python 3.12, FastAPI, SQLAlchemy 2 (typed ORM), Pydantic v2, Alembic |
| Database   | PostgreSQL 16 + PostGIS 3.4 (primary). SQLite is a supported zero-config fallback for development and tests. |
| Geospatial | rasterio, xarray, geopandas, numpy, pandas, shapely |
| Jobs       | Database-backed queue + polling worker threads (no external broker) |
| Deploy     | Docker Compose (PostGIS + backend + frontend/nginx) |

```
mini2/
├─ backend/                 FastAPI application
│  ├─ app/
│  │  ├─ api/               HTTP routers + serializers
│  │  ├─ core/              config, database, security, permissions, deps, enums
│  │  ├─ models/            SQLAlchemy models
│  │  ├─ schemas/           Pydantic request/response schemas
│  │  ├─ providers/         external data-source adapters (7)
│  │  ├─ processing/        raster IO, masks, composites, quality rules
│  │  ├─ indicators/        indicator computers
│  │  └─ services/          business logic (users, audit, jobs, ingestion, …)
│  ├─ alembic/              migrations
│  ├─ tests/                pytest suite
│  └─ pyproject.toml
├─ frontend/                React + TypeScript SPA
│  └─ src/{pages,components,lib,auth}/
├─ data/storage/            raw / processed / exports / reports (git-ignored)
├─ docker-compose.yml
├─ .env.example             Compose environment template
└─ README.md
```

---

## 2. Quick start (Docker Compose)

> Requires Docker with Compose v2. The PostGIS volume persists the database.
> For production servers (TLS, systemd, backups, hardening checklist) see
> **[DEPLOYMENT.md](DEPLOYMENT.md)**.

```bash
cp .env.example .env
# Edit .env and set a strong SECRET_KEY:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up --build
```

Then create the first administrator:

```bash
docker compose exec backend python -m app.cli bootstrap-admin \
  --email admin@example.org --name "System Administrator"
# You will be prompted for a password (minimum 10 characters).
```

| Service  | URL |
|----------|-----|
| Frontend | http://localhost:8080 |
| API docs | http://localhost:8000/docs |
| Health   | http://localhost:8000/health |

On startup the backend applies migrations are **not** run automatically when
`AUTO_CREATE_TABLES=false`; for a fresh Compose database either leave the
defaults (`AUTO_CREATE_TABLES=true`) or run `docker compose exec backend alembic upgrade head`.

---

## 3. Local development (no Docker)

### 3.1 Backend

Python 3.12 is required. `uv` is recommended.

```bash
cd backend
cp .env.example .env            # optional; sensible defaults apply

# create and populate the virtual environment
uv venv --python 3.12
uv pip install -e ".[dev]"      # or: uv sync

# database — pick ONE
#   a) PostgreSQL + PostGIS (primary)
#      DATABASE_URL=postgresql+psycopg://lakewatch:lakewatch@localhost:5432/lakewatch
#   b) SQLite (zero-config, used by the tests)
#      DATABASE_URL=sqlite:///./dev.db

# create schema (development) and seed roles/indicators/default study area
python -m app.cli create-tables
python -m app.cli bootstrap

# create the first administrator
python -m app.cli bootstrap-admin --email admin@example.org --name "Admin"

# run the API (auto-reload)
uvicorn app.main:app --reload --port 8000

# optional: run background workers in the foreground instead of in-process
python -m app.cli worker
```

### 3.2 Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The Vite dev server proxies `/api` to `http://localhost:8000`, so the frontend is
same-origin by default (no CORS configuration needed for development).

Other scripts: `npm run build` (type-check + production bundle),
`npm run typecheck`, `npm run lint`, `npm run preview`.

---

## 4. Environment variables

All backend settings are read by `backend/app/core/config.py`. The full
authoritative list lives in **`backend/.env.example`**; Compose-level variables
are in the root **`.env.example`**.

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_NAME` | `LakeWatch API` | API title |
| `ENVIRONMENT` | `development` | `development` / `production` |
| `DATABASE_URL` | `sqlite:///…/dev.db` | Primary DB. Use `postgresql+psycopg://…` for PostGIS. |
| `AUTO_CREATE_TABLES` | `true` | Create missing tables on startup (dev). Set `false` in production. |
| `STARTUP_BOOTSTRAP` | `true` | Seed roles/permissions, default study area, indicator definitions on startup. |
| `SECRET_KEY` | insecure dev value | **Required in production.** JWT signing key. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Access-token lifetime. |
| `BCRYPT_ROUNDS` | `12` | Password hashing cost. |
| `BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` / `_NAME` | *(empty)* | Consumed by `bootstrap-admin`; blank ⇒ prompted. |
| `STORAGE_ROOT` | `../data/storage` | Root for `raw/`, `processed/`, `exports/`, `tmp/`. |
| `JOBS_ENABLED` | `true` | Run in-process job workers. Set `false` in tests. |
| `JOBS_POLL_INTERVAL_SECONDS` | `2.0` | Worker poll interval. |
| `JOBS_WORKER_COUNT` | `2` | Worker threads. |
| `JOBS_MAX_ATTEMPTS` | `3` | Retry attempts per job. |
| `HTTP_TIMEOUT_SECONDS` | `30.0` | Outbound provider HTTP timeout. |
| `CHIRPS_BASE_URL` | CHC CHIRPS v2.0 | CHIRPS adapter base URL. |
| `NASA_POWER_BASE_URL` | NASA POWER API | NASA POWER adapter base URL. |
| `PLANETARY_COMPUTER_STAC_URL` | MPC STAC | Microsoft Planetary Computer STAC endpoint. |
| `PLANETARY_COMPUTER_SAS_URL` | MPC SAS | Planetary Computer SAS token endpoint. |
| `LPDAAC_STAC_URL` | LP DAAC STAC | USGS LP DAAC STAC endpoint. |
| `AI_BASE_URL` | *(empty)* | Optional OpenAI-compatible chat-completions base URL; blank disables AI. |
| `AI_MODEL` | *(empty)* | Model name for the dashboard assistant. |
| `AI_API_KEY` | *(empty)* | Server-side provider key; never sent to the browser. |
| `AI_TIMEOUT_SECONDS` | `45` | Maximum wait for the assistant provider (1–120 seconds). |
| `CORS_ORIGINS` | `localhost:5173,127.0.0.1:5173,localhost:8080` | Comma-separated allowed browser origins. |

Compose-only variables: `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`.

The assistant sends only the dashboard summary metrics and the submitted
question to the configured provider after a user asks a question; it does not
send raw satellite files or unpublished map layers. For Docker Compose, set
`AI_BASE_URL`, `AI_MODEL` and (when required) `AI_API_KEY` in the root `.env`.
The map uses OpenStreetMap tiles and a simplified Lake Malawi shoreline from
OpenStreetMap; attribution is shown on the map.

---

## 5. Database schema & migrations

Migrations are managed with **Alembic** from `backend/`.

```bash
cd backend

alembic upgrade head          # apply all migrations
alembic downgrade -1          # roll back one revision
alembic downgrade base        # roll back to empty
alembic current               # show the applied revision
alembic check                 # verify models and migrations agree
alembic revision --autogenerate -m "describe the change"
```

Two revisions exist:

- `ba20bc51427c_initial_schema.py` — all tables.
- `b53fc8e8dafe_postgis_extension_and_spatial_indexes.py` — enables the PostGIS
  extension and creates spatial indexes. It is a no-op on SQLite.

**PostGIS note.** Spatial data (study-area boundaries, dataset coverage, product
bboxes) is stored in a GeoJSON-typed column that maps to `TEXT` on SQLite and to
PostGIS `geometry` when PostGIS is available. `app/services/spatial.py` detects
availability and pushes spatial filters down to PostGIS when possible;
otherwise it filters in Python. Geometry is always EPSG:4326.

---

## 6. API documentation

- **Interactive (Swagger UI):** `http://localhost:8000/docs`
- **OpenAPI JSON:** `http://localhost:8000/openapi.json`

All endpoints are versioned under **`/api/v1`**. Unversioned `GET /health` is the
liveness probe. Access control is **deny-by-default**: every protected endpoint
requires an explicit permission and the backend is the authority (the UI only
hides what a user cannot use).

### 6.1 Permission model

Three roles: `super_admin`, `admin`, `researcher`. Role → permission mapping is
code-defined in **`backend/app/core/permissions.py`** and is not editable through
the API (the roles endpoint is read-only).

| Permission | super_admin | admin | researcher |
|------------|:-----------:|:-----:|:----------:|
| `admin.users.read` | ✔ | ✔ | |
| `admin.users.write` | ✔ | ✔ | |
| `admin.roles.read` | ✔ | ✔ | |
| `admin.data_sources.read` / `.write` / `.test` | ✔ | ✔ | |
| `admin.thresholds.read` / `.write` | ✔ | ✔ | |
| `admin.audit.read` | ✔ | ✔ | |
| `research.datasets.read` | ✔ | ✔ | ✔ |
| `research.ingest.run` | ✔ | | ✔ |
| `research.processing.run` | ✔ | | ✔ |
| `research.indicators.read` | ✔ | ✔ | ✔ |
| `research.compare.run` | ✔ | | ✔ |
| `research.exports.create` | ✔ | ✔ | ✔ |
| `research.exports.download` | ✔ | ✔ | ✔ |
| `disaster.alerts.read` | ✔ | ✔ | ✔ |
| `disaster.alerts.respond` | ✔ | ✔ | ✔ |
| `disaster.evaluate.run` | ✔ | ✔ | |
| `reports.read` | ✔ | ✔ | ✔ |
| `reports.create` | ✔ | ✔ | ✔ |
| `reports.download` | ✔ | ✔ | ✔ |
| `public.publish` | ✔ | ✔ | |

Existing databases pick up new permission rows automatically at next startup
(bootstrap is idempotent).

`super_admin` holds the wildcard `*`, which is expanded to the concrete list in
API responses.

Privilege-escalation guards (enforced in `app/services/users.py`):
only a `super_admin` may grant or revoke `super_admin`; a plain administrator
cannot modify a `super_admin` account or grant roles at/above their own level;
administrators cannot change their own roles or activation state; and the last
active administrator cannot be deactivated or demoted.

### 6.2 Endpoint groups

| Group | Base path | Highlights |
|-------|-----------|-----------|
| Auth | `/api/v1/auth` | `login`, `me`, `change-password`, `password-reset/request`, `password-reset/confirm` |
| Users & roles | `/api/v1/admin` | `users` CRUD-ish (create, patch, activate, deactivate, roles, password-reset), `roles`, `permissions` |
| Data sources | `/api/v1/admin/data-sources` | create/patch/delete, `POST /{id}/test` connection test |
| Thresholds | `/api/v1/admin/thresholds` | create/patch/delete, `GET /{id}/versions` |
| Audit | `/api/v1/admin/audit` | list (filterable), `actions`, `resource-types` |
| Providers | `/api/v1/providers` | `list`, `catalogue`, `{key}` |
| Study areas | `/api/v1/study-areas` | list/create/get/patch/delete |
| Datasets | `/api/v1/datasets` | list (filters), `quality-flags`, `{id}` detail |
| Jobs | `/api/v1/jobs` | list, get, `cancel`, `retry` |
| Ingestion | `/api/v1/ingestion` | create job, list, get |
| Processing | `/api/v1/processing` | `operations`, create run, `runs`, `runs/{id}` |
| Indicators | `/api/v1/indicators` | `definitions`, `compute`, `results`, `results/{id}` |
| Analysis | `/api/v1/analysis` | `GET /timeseries`, `POST /compare` |
| Exports | `/api/v1/exports` | create, list, get, `{id}/download` |
| Disaster | `/api/v1/disaster` | `POST /evaluate`, `alerts` (list/detail), `acknowledge`, `notes`, `resolve`, `reopen`, `forecasts` (list/create) |
| Reports | `/api/v1/reports` | create (queued build), list, get (incl. frozen summary snapshot), `{id}/download` (PDF / CSV), cancel, retry |
| Public data | `/api/v1/public` | **anonymous**: `overview`, `datasets`, `alerts`, `map` (GeoJSON of published study areas); **staff-only PATCH** `{entity}/{id}` publish toggles (`public.publish`) |

---

## 7. Provider integration status

Seven adapters are implemented and were verified against the live endpoints
(2026-10-21). **None require an API key** — all are open endpoints. Automated
tests exercise them with a mocked HTTP transport, so the core suite never needs
network access or paid services.

| Provider key | Source | Product | Status |
|--------------|--------|---------|--------|
| `sentinel2_mpc` | Microsoft Planetary Computer (STAC + SAS) | Sentinel-2 L2A | tested |
| `landsat_mpc` | Microsoft Planetary Computer | Landsat 8/9 C2 L2 | tested |
| `modis_mpc` | Microsoft Planetary Computer | MODIS reflectance | tested |
| `modis_lst_mpc` | Microsoft Planetary Computer | MODIS land-surface temperature | tested |
| `sentinel3_sral` | Microsoft Planetary Computer | Sentinel-3 SRAL altimetry | tested |
| `chirps` | Climate Hazards Center, UCSB | CHIRPS v2.0 daily rainfall | tested |
| `nasa_power` | NASA POWER | Meteorology / climate (point) | tested |

Retrieval strategy: rasters are read **windowed** to the study-area bounding box
and bounded by `ingestion_config.max_dim` (default 2048) so continental scenes
are never loaded whole. Documented per-product scale/offset are applied at
retrieval, so stored values are in physical units. Non-raster assets (netCDF,
CSV, JSON) and compressed bundles are downloaded whole with SHA-256 provenance;
CHIRPS `.tif.gz` bundles are checksummed, decompressed and windowed.

---

## 8. Algorithms, indicators & assumptions

### 8.1 Indicator catalogue

Ten indicator keys are seeded (definitions are data, not hard-coded results):

| Indicator | Unit | Notes |
|-----------|------|-------|
| `water_extent` | km² | Planimetric water area from MNDWI/NDWI |
| `water_extent_change` | km² / % | Depends on `water_extent` |
| `water_level_altimetry` | m | From Sentinel-3 SRAL (needs NetCDF4/HDF5) |
| `chlorophyll_a_proxy` | µg/L | **Proxy** — unvalidated |
| `turbidity_proxy` | NTU-equiv | **Proxy** — unvalidated |
| `surface_water_temperature` | °C | MODIS LST |
| `rainfall_summary` | mm | CHIRPS |
| `rainfall_anomaly` | mm / % | CHIRPS vs. climatology |
| `temperature_summary` | °C | NASA POWER |
| `temperature_anomaly` | °C | NASA POWER vs. climatology |

### 8.2 Documented methods

- **Water masking** — MNDWI (Xu, 2006) `(Green − SWIR1)/(Green + SWIR1)` and
  NDWI (McFeeters, 1996) `(Green − NIR)/(Green + NIR)`. Default threshold `0.0`
  is a common documented choice and is flagged **provisional**; it is
  configurable per run and recorded in each result's provenance.
- **Turbidity index** — NDTI (Lymburner et al., 2016).
- **Harmonization** — the default is the **identity transform**. Coefficients for
  cross-sensor harmonization are applied only when the user supplies cited
  coefficients (`app/processing/harmonize.py`); nothing is invented.

### 8.3 Quality flags

Rules are versioned (`1.0.0`) and evaluated in priority order:
`MISSING_DATA` → `PROCESSING_FAILED` → `INSUFFICIENT_COVERAGE` →
`CLOUD_CONTAMINATED` → `LOW_QUALITY` → `UNVALIDATED` → `VALID`.

| Rule | Threshold |
|------|-----------|
| Insufficient coverage | valid fraction < 50 % |
| Low quality (coverage) | valid fraction < 80 % |
| Cloud contaminated | cloud fraction > 50 % |
| Low quality (cloud) | cloud fraction > 10 % |
| Missing | valid fraction ≤ 0.1 % |

`unvalidated` is set **only** for proxy outputs (chlorophyll-a, turbidity);
water-extent, altimetry and climate indicators use coverage/cloud/missing rules.

### 8.4 Honesty rules

- **Never fabricate.** When an indicator cannot be computed, the result row stores
  `value = NULL` with an explicit reason — never `0`.
- **Observed vs. derived** data are distinguished (`Dataset.kind`:
  `observed` / `composite` / `processed`), and raw vs. processed is tracked with
  `Dataset.is_raw`.
- **Water extent ≠ water level.** Water extent is a planimetric *area*; altimetry
  is a *level*. The UI and provenance strings say so explicitly.
- **Provisional defaults are labelled** as such in the UI (`ProvisionalNote`) and
  in threshold rows (`is_provisional`).

### 8.5 Disaster alert evaluation (documented defaults)

The comparison engine lives in `app/services/disaster.py`; its rules are
deliberately explicit:

1. **Which thresholds.** Only `approved` thresholds are evaluated by default;
   provisional ones participate only when the request sets
   `include_provisional: true`, and such alerts are labelled *provisional* in
   their message. Alerts snapshot the threshold (operator, values, version,
   approval) at breach time, so later threshold edits never rewrite history.
2. **Which values.** For each (study area, thresholded indicator): the latest
   recorded forecast value takes precedence; otherwise the latest computed
   indicator result with a non-null value is used (`metric_source` is recorded
   as `forecast` or `observed`). Pairs without data are **skipped and
   reported**, never invented.
3. **Breach rule.** `gt`/`gte` ⇒ value exceeds `value_low`; `lt`/`lte` ⇒ value
   is below `value_low`; `between` ⇒ `value_low..value_high` is the *normal
   band*, anything outside it breaches.
4. **Severity (provisional bands).** Severity is derived from exceedance:
   ≥ 25 % beyond the threshold reference (or 25 % of the band width for
   `between`) ⇒ `critical`, otherwise `warning` — so the discrete
   `info/warning/critical` levels are #1 severity levels and `flood` /
   `drought` / `water_quality` / `general` is a separate hazard type.
5. **Hazard type (provisional mapping).** High water level / water extent /
   heavy rainfall ⇒ `flood`; low rainfall / shrinking extent / low water level
   ⇒ `drought`; high chlorophyll-a or turbidity proxies ⇒ `water_quality`;
   temperature anomalies and anything unmapped ⇒ `general`.
6. **Deduping & escalation.** While an alert for the same (study area,
   indicator, threshold) is open/acknowledged, re-evaluation updates it —
   latest value, `times_seen` counter, severity escalation (never automatic
   downgrade) — and appends a *Re-evaluated* note to its response history.
7. **Response record.** Acknowledge / note / resolve / reopen each create an
   append-only `AlertResponse` row plus an audit event; the alert keeps
   acknowledged-by / resolved-at attributions.

### 8.6 Report generation (build-time snapshot semantics)

Reports are produced by the registered background job `report.build` (`app/services/reports.py`);
the row in `reports` records the request, and `summary_json` freezes every figure
at build time. The rendered file is written once into
`<storage>/reports/<YYYY>/<MM>/<uuid>/` and never regenerated, so a distributed
report stays auditable even if underlying data changes later.

1. **Periods.** `periodic` reports derive their window from a calendar preset
   (`daily/weekly/monthly/quarterly/annual`); every preset **ends today** — the
   platform never claims future data. `custom` reports require explicit
   `period_start`/`period_end` (validated `start ≤ end`).
2. **Sections.** The request selects any subset of `overview` (study areas,
   datasets overlapping the period, approved/provisional threshold counts),
   `indicators`, `forecasts`, `alerts`. Optional filters: `study_area_id` and
   `indicator_keys` (validated against the catalogue).
   Queued builds can be canceled before a worker starts them; failed or canceled
   reports can be retried from the report history.
3. **Indicator statistics.** There is no statistics module — the `indicators`
   section is the documented *summary statistics* computed at build time from
   stored `IndicatorResult` rows in the window: result count (including
   NULL-valued rows), computed count, min / mean / max, first & last values
   with dates, a first→last "direction" word, and the quality-flag
   distribution. NULL-valued results are counted but never zeroed.
4. **Forecasts.** User-recorded `ForecastValue` rows whose `target_date` falls
   in the period, listed verbatim with their provenance note. The report does
   not generate forecasts and no ML is involved.
5. **Alerts.** Alerts `first_seen` in the period: total, counts by hazard kind /
   severity / status, highest severity, and up to 20 sample alerts (severity-
   ordered), plus which responses were recorded — the same aggregates the
   alerts UI shows.
6. **Formats.** PDF via **reportlab** (plain professional layout: title block,
   provenance paragraph, one table per section — no charts). CSV is a
   long-format table (`section, name, metric, value, unit, detail`,
   UTF-8-sig) with the same content; empty sections emit an explicit
   `none in period` row.
7. **Permissions.** `reports.create` to queue (returns 202 + the queued
   report), `reports.read` to list/view (GET detail includes the frozen
   `summary_json`), `reports.download` to fetch the finished file
   (422 until the job has succeeded). `admin` and `researcher` hold all
   three; reports expose only aggregates these roles can already read.
8. **Audit.** `report.request` on queue, `report.complete` on finished build;
   failures persist `status = failed` + an error message once retries are
   exhausted.

### 8.7 Public data (default-private, publish-by-decision)

The public dashboard is served by **anonymous, read-only** endpoints in
`app/api/public.py`. The access rule is deliberately narrow:

1. **Nothing is public by default.** `Dataset`, `StudyArea` and `Alert` each
   carry an `is_public = False` flag. Anonymous queries filter strictly on
   ``is_public = True`` — a factory-reset database serves an empty dashboard.
2. **Publishing is a staff decision.** `PATCH /api/v1/public/{entity}/{id}`
   with `{"is_public": true|false}` requires the `public.publish` permission
   (`super_admin`/`admin`) and writes an audit event (`dataset.publish`,
   `alert.publish`, `study_area.publish` and their `unpublish` counterparts).
   Unpublishing removes the row from every public view immediately.
3. **Minimum-necessary fields.** Public serializers expose only what the
   public needs: dataset metadata (never file paths, checksums, provenance
   payloads or data-source configuration) and alert facts (kind, severity,
   status, message, value and provenance — never threshold snapshots or staff
   names). A study area's *name* is itself public information only when that
   area is published; until then published records referencing it show no
   area name.
4. **Map.** `GET /public/map` returns a GeoJSON FeatureCollection of published
   study areas with per-area public counts (published datasets, active
   published alerts by severity, highest active severity) — no investigation
   data beyond that.
5. **Honesty.** The dashboard narrative repeats the platform's honesty rules:
   no forecasting is performed, proxy-derived values are labelled unvalidated,
   and every figure traces to a stored platform record.

---

## 9. Testing

The backend suite uses **pytest** and never touches the network (provider HTTP is
replaced by an `httpx.MockTransport`; background workers are disabled). Each run
uses a fresh temporary SQLite database and storage root.

```bash
cd backend
pytest                       # whole suite
pytest tests/test_auth_rbac.py -v
pytest -k indicators
```

The `tests/conftest.py` fixtures provide a `TestClient`, admin/researcher auth
headers, a `make_user` factory, the default study area, and a
`synthetic_geotiff` factory for building small in-AOI rasters.

Coverage includes: auth & RBAC, privilege escalation, data-source configuration,
threshold versioning, audit access, ingestion (mocked success/failure),
preprocessing, indicators, quality flags, filtering/comparison, exports, the
disaster module (evaluation matrix, dedupe/escalation, severity/hazard
mapping, the full response workflow, forecast provenance validation, and
permission boundaries) in `tests/test_disaster.py` — and the report module
(period derivation, build-time aggregate correctness including NULL handling,
section selection, PDF/CSV downloads, validation rules, permissions and the
queued-download rejection) in `tests/test_reports.py`.

```bash
# lint the backend (ruff is deliberately not part of the [dev] extra)
cd backend
uvx ruff check .        # or: pip install ruff && ruff check .
```

---

## 10. Run commands summary

| Task | Command |
|------|---------|
| Start everything (Docker) | `docker compose up --build` |
| Apply migrations | `cd backend && alembic upgrade head` |
| Create a super admin | `cd backend && python -m app.cli bootstrap-admin --email you@example.org` |
| Run the API | `cd backend && uvicorn app.main:app --reload --port 8000` |
| Run workers only | `cd backend && python -m app.cli worker` |
| Run one job | `cd backend && python -m app.cli run-job <job_id>` |
| Run tests | `cd backend && pytest` |
| Frontend dev server | `cd frontend && npm run dev` |
| Frontend production build | `cd frontend && npm run build` |

---

## 11. Known limitations

- **NetCDF3 altimetry:** SQLite installations lack a scipy engine, so classic
  NetCDF3 altimetry files cannot be read; such jobs record a clear *failed*
  result rather than a wrong number. HDF5/netCDF4 files are supported.
- **Provisional thresholds:** water-mask threshold `0.0`, coverage/cloud limits
  and all indicator defaults are documented but **not calibrated for Lake
  Malawi**. They are labelled provisional throughout.
- **Proxies are unvalidated:** chlorophyll-a and turbidity are remote-sensing
  proxies, flagged `UNVALIDATED` and never presented as in-situ measurements.
- **Docker artifacts untested locally:** `docker-compose.yml`, both Dockerfiles
  and `frontend/nginx.conf` are authored but were not built or run in this
  environment (Docker was unavailable). `docker compose config` is recommended
  before first deployment.
- **Report PDFs are text + tables only:** reportlab renders a professional
  plain layout (title block, provenance, one table per section); there are no
  embedded charts. The CSV is a long-format table for machine reading rather
  than a visual one-pager.
- **Reports are a frozen snapshot:** `summary_json` and the stored file are
  written once at build time. Nothing regenerates or schedules them — a
  "periodic" report is built on demand with a calendar window, not by cron.
  If underlying data changes later, previously distributed reports stay as
  they were (by design).
- **The public dashboard shows metadata, not files:** published datasets
  expose their record (title, period, quality, provenance-class) but never
  the stored raster/file itself; downloads remain internal to the staff
  console. Until a dedicated public file-approval flow exists, that is the
  safe reading of "public read-only access to approved data".
- **Disaster analytics are provisional:** hazard-type mapping and severity bands
  are documented code defaults (`app/services/disaster.py`), not locally
  validated response thresholds. Alerts store the exact metric and threshold so
  records stay auditable regardless of how the bands are later recalibrated.
- **No forecast generation:** forecast values are user-entered with mandatory
  provenance; alerts record `metric_source = forecast` vs `observed` so records
  cannot be confused with computed observations.
- **Single-node job queue:** jobs are DB-backed with polling workers; this is
  adequate for a single instance but is not a distributed scheduler (no
  priority queues or cron).
- **Spatial pushdown is optional:** with PostGIS the spatial filters run in the
  database; on SQLite they run in Python, which is fine for the AOI-sized data
  this system handles but does not scale to country-wide scans.

---

## 12. Licence & attribution

Data products remain subject to their providers' terms:
Copernicus Sentinel (ESA), Landsat & MODIS (USGS/NASA), CHIRPS (Climate Hazards
Center, UCSB) and NASA POWER. Scientific methods are cited in
`app/processing/` and in each indicator definition.
