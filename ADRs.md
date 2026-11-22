# Architectural Decision Records (ADRs) – LakeWatch

## ADR‑01 – Data‑Source Registration via Provider Adapters
**Status:** Accepted  
**Context:** The system must ingest raster data from seven open‑access providers (CHIRPS, Sentinel‑2, MODIS, etc.). No central catalogue existed; each provider had a different API pattern.  
**Decision:** Implement a generic `Provider` base class in `backend/app/providers/` with concrete subclasses for each product. Register each adapter in `registry.py` and expose a unified `ingest(key, study_area)` endpoint.  
**Consequences:**  
- New code (~150 loc) but gives future‑proof addition of new providers.  
- All adapters must pass the same unit‑test suite (see SRS FR‑01, FR‑16).  
- Slight increase in docker image size (negligible).

## ADR‑02 – Cloud‑Masking using Quality Flags from Provider Metadata
**Status:** Accepted  
**Context:** Raw satellite scenes often contain > 50 % cloud cover; presenting unmasked water‑level values would mislead planners.  
**Decision:** Use the provider‑supplied `cloud_fraction` metadata to set the `quality_flag` (`CLOUD_CONTAMINATED` > 50 %, `LOW_QUALITY` > 10 %). Flagged results are never displayed as “observed”; UI shows a “cloud‑gap” badge and the underlying value is marked `interpolated = false`.  
**Consequences:**  
- Guarantees honesty rule (no fabrication).  
- Requires each provider to expose cloud fraction; if missing, fallback to default `UNVALIDATED` flag.  
- Slight increase in storage (`quality_flag` column).

## ADR‑03 – Unit‑Metadata Discipline (Pint + Pydantic)
**Status:** Accepted  
**Context:** Historical bugs (e.g., metre vs. centimetre) have caused downstream mis‑interpretation in disaster alerts.  
**Decision:** Adopt **Pint** (Python unit registry) in all indicator‑result models. Every `value` field is paired with a `Unit` enum; CI runs a *unit‑consistency* test that enforces metre/kilometre consistency.  
**Consequences:**  
- Guarantees FR‑18/ FR‑19.  
- Existing test suite must be updated (add TEST‑U1).  
- Minimal runtime overhead; unit conversion automatic when needed.

## ADR‑04 – Validation of Indicators Against In‑Situ Gauge Records
**Status:** Partial (to be completed)  
**Context:** The platform currently has no integration with Malawi gauge stations; RMSE reporting is missing (property 1 of Signature Challenge).  
**Decision:** Add a new data‑source `malawi_gauges` (CSV/PostGIS) and a daily job that interpolates gauge readings to the nearest lake‑pixel, computes RMSE against the latest `water_level_altitude` indicator, and stores the result in a `validation_metrics` table.  
**Consequences:**  
- Provides the missing evidence for FR‑18 property 1.  
- Requires coordination with Meteorological Service (data sharing agreement).  
- Adds a modest background worker; RMSE computed per study area per day.

## ADR‑05 – Risk Classification Derived from Documented Threshold Tables
**Status:** Accepted  
**Context:** Flood/drought severity currently uses hard‑coded percentages, making it fragile to threshold changes.  
**Decision:** Store **all** flood/drought thresholds in the `thresholds` table (already present). The disaster engine (`disaster.py`) must **only** read from this table and **never** embed magic numbers. The severity logic (`≥ 25 % beyond threshold → critical`) is derived from the table’s `operator` and `value_low`/`value_high`.  
**Consequences:**  
- Guarantees FR‑19.  
- Future threshold changes propagate instantly; no code redeploy needed for numeric adjustments.  
- Adds a small validation layer in the API to reject any “hard‑coded” severity calculation.