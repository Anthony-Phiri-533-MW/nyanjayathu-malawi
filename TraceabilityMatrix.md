# Traceability Matrix – Requirement → Code → Test

| Req‑ID | Requirement (short) | Implementation (code module / file) | Gherkin Test(s) |
|--------|----------------------|--------------------------------------|-----------------|
| FR‑01 | Ingest CHIRPS daily rasters | `backend/app/providers/chirps.py`; `app/services/ingestion.py` | TEST‑01 (indirect) |
| FR‑05 | Persist unit, sensor, date, version | `backend/app/models/indicator_result.py` (Pydantic) | TEST‑01 |
| FR‑11 | AI endpoint strips geometry | `backend/app/api/public.py` – `POST /public/interpret-metrics` | TEST‑02 (cloud‑mask) |
| FR‑07 | Alert engine vs approved thresholds | `backend/app/services/disaster.py` | TEST‑03 |
| FR‑08 | Public filter on `is_public` | `backend/app/api/public.py` – `GET /public/datasets` | TEST‑04 |
| FR‑18 | Unit‑mismatch caught by tests | `tests/unit/test_indicator_units.py` | TEST‑05 |
| FR‑19 | Flood/drought from documented thresholds | `backend/app/services/disaster.py` + threshold CSV files | TEST‑03 |
| FR‑20 | Cloud gaps flagged, never raw obs | `backend/app/processing/quality_flags.py` | TEST‑02 |
| FR‑12 | Report snapshot freeze | `backend/app/services/reports.py` | TEST‑07 |
| FR‑13 | Super‑admin permission CRUD | `backend/app/core/permissions.py` | TEST‑06 (audit) |
| FR‑14 | Role‑based UI hiding | `frontend/src/components/LakeMapPanel.tsx` + RBAC logic | TEST‑08 |
| FR‑22 | Daily scheduler runs at 02:00 UTC | `backend/app/jobs/daily_scheduler.py` | TEST‑09 |
| FR‑16 | SHA‑256 checksum stored | `backend/app/services/ingestion.py` | TEST‑10 |
| FR‑02 | Sentinel‑2 water‑extent MNDWI | `backend/app/indicators/water_extent.py` | TEST‑01 |
| FR‑03 | MODIS LST temperature | `backend/app/indicators/temperature.py` | TEST‑02 |
| FR‑15 | New public overview endpoint | `backend/app/api/public.py` – `GET /public/overview` | (new test – maps to FR‑15) |
| FR‑17 | Multiple study areas support | `backend/app/models/study_area.py` | (new test) |
| FR‑21 | Health probe with data‑source status | `backend/app/main.py` – `GET /health` | (smoke test) |

*The matrix can be rendered as a spreadsheet or a Markdown table; each row maps a requirement to the exact source file (or database schema element) and the Gherkin scenario that validates it.*