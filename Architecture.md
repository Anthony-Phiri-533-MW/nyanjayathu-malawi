# As‑Built Architecture (C4 Model)

## 1. Context Diagram

| Element | Description |
|---------|-------------|
| **External Actors** | • *Malawi Meteorological Service* – gauge records (ground truth).<br>• *Satellite Providers* – CHIRPS, Sentinel‑2, MODIS, NASA POWER (open APIs).<br>• *Disaster Planners* – use the public dashboard and receive alerts.<br>• *Site Administrators* – manage users, thresholds, data sources. |
| **System Boundary** | **LakeWatch** – full‑stack monitoring platform (frontend + backend + DB). |
| **Relationships** | • Actors → API (`/api/v1/…`) – HTTPS, JWT‑auth for staff; anonymous for public endpoints.<br>• System → External PostgreSQL/PostGIS database.<br>• System → External Satellite STAC services.<br>• System → AI Service (OpenRouter/Nemotron) via `/public/interpret-metrics`. |

```
  +---------------------+        +---------------------+
  |   Satellite Providers|        |   Malawi Gauge Data |
  +----------+----------+        +----------+----------+
               \                      /
                \                    /
                 \      LakeWatch    /
                  +------------+------+
                  |  Frontend (React) |
                  |  Backend (FastAPI) |
                  +------------+------+
                               |
               +-----------+-----------+
               |  PostgreSQL + PostGIS |
               +-----------------------+
```

## 2. Container Diagram

| Container | Technology | Primary Responsibility |
|-----------|------------|------------------------|
| **Frontend (React 18 + Vite)** | `frontend/src/` | UI, map, KPI cards, AI interpretation panel, role‑based visibility. |
| **Backend API (FastAPI)** | `backend/app/` | Request validation (Pydantic), business logic, indicator computation, disaster evaluation, report generation, public endpoints. |
| **Database (PostgreSQL 16 + PostGIS 3.4)** | `data/storage/` | Persistent storage of datasets, indicator results, thresholds, audit logs, study areas, users/roles. |
| **Provider Adapters** | `backend/app/providers/` (7 adapters) | Wrap STAC/SAS endpoints, windowed raster download, SHA‑256 checksum, quality‑flag evaluation. |
| **Job Worker (SQL‑polling)** | `backend/app/workers/` | Poll DB queue, run ingestion, processing, indicator recomputation, daily scheduler. |
| **AI Interpretation Service** | OpenRouter → Nemotron (`AI_BASE_URL`, `AI_MODEL`) | Anonymous metric explanation; geometry is stripped before sending. |
| **Cache / Static Assets** | `nginx` (Docker) | Serve SPA, TLS termination, asset compression. |

### Key Data Flows

1. **Ingestion** → Provider adapter downloads raster → stores `Dataset` row + SHA‑256 → worker enqueues processing job.  
2. **Processing** → Indicator computer (e.g., MNDWI) writes `IndicatorResult` rows with unit, sensor, version.  
3. **Disaster Evaluation** → `disaster.py` reads latest indicator values, compares to approved thresholds → creates/updates `Alert`.  
4. **Public Dashboard** → Anonymous GET endpoints read only `is_public = true` rows; AI panel sends sanitized summary (no raw geometry).  
5. **Report Generation** → `report.build` job freezes `summary_json` at build time → PDF/CSV exported.