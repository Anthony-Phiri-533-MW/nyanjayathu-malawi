# Signature‑Challenge Gap Analysis

## Property 1 – Validation against gauge records with RMSE

| Aspect | As‑built system | Missing / Not yet | Evidence |
|--------|----------------|-------------------|----------|
| Gauge‑record ingestion | None | No pipeline to import Malawi gauge stations | No code in `backend/app/providers/` for gauges; no `validation_metrics` table |
| RMSE computation | None | No RMSE calculation between indicator values and ground truth | N/A |
| **Prove** | – | **Automated test** (TEST‑V1) + **live demo**: upload gauge CSV, run `python -m app.cli validate‑gauges`, query `GET /api/v1/validation-metrics` → see RMSE values |

## Property 2 – Units and provenance (unit, sensor, date, version); tests catch mix‑ups

| Aspect | As‑built system | Missing / Not yet | Evidence |
|--------|----------------|-------------------|----------|
| Pydantic model has `unit`, `sensor`, `date`, `processing_version` | Present (fields exist) | No runtime validation using Pint; no test that fails on `"cm"` vs `"m"` | `indicator_result.py` defines `unit: str` but no Pint constraint |
| **Prove** | – | **Automated test** (TEST‑U1) + **live demo**: create `IndicatorResult(value=1500, unit="cm")`, run `pytest -k unit_consistency`, observe failure; fix model, test passes |

## Property 3 – Risk classification from documented thresholds, with confusion matrix on historical events

| Aspect | As‑built system | Missing / Not yet | Evidence |
|--------|----------------|-------------------|----------|
| Threshold table exists, disaster engine reads it | Present | No historical event data; no confusion‑matrix computation | `disaster.py` has hard‑coded 25 % rule, no `historical_events` table |
| **Prove** | – | **Automated test** (TEST‑R1) + **live demo**: seed 20 historic pairs, run `python -m app.cli compute‑confusion-matrix`, call `GET /api/v1/risk-matrix` → JSON matrix |

## Property 4 – Cloud gaps: masked, interpolated, flagged, never shown as observations

| Aspect | As‑built system | Missing / Not yet | Evidence |
|--------|----------------|-------------------|----------|
| Quality‑flag sets `CLOUD_CONTAMINATED` when `cloud_fraction > 50 %` | Present | No interpolation; `gap_interpolated` column missing; UI may render `NULL` as 0 | `quality_flags.py` only sets flags; schema lacks `gap_interpolated` |
| **Prove** | – | **Automated test** (TEST‑C1) + **live demo**: ingest MODIS scene with high cloud, run worker, query result row → verify `quality_flag` and `gap_interpolated`; UI shows badge |

## How to close the remaining 30 %

| Gap | Concrete step (implementation plan) |
|-----|--------------------------------------|
| **Validation (RMSE against gauges)** | 1. Acquire Malawi gauge daily water‑level CSV from the Department of Water Development.<br>2. Add a new provider `malawi_gauges` following the pattern of other adapters.<br>3. Create a daily job that (a) matches the nearest gauge to each lake‑pixel, (b) computes `RMSE = sqrt(mean((indicator‑value‑gauge)²))`, (c) stores the result in `validation_metrics`.<br>4. Write the Gherkin test `TEST‑V1` and add it to CI. |
| **Units & provenance** | 1. Add **Pint** as a runtime dependency (`uv pip install pint`).<br>2. Modify `IndicatorResult.unit` to be a `pint.Unit` object; add a validator that raises on mismatch.<br>3. Add TEST‑U1 to the test suite; run `pytest` to confirm failure on `"cm"` and pass on `"m"`. |
| **Risk classification + confusion matrix** | 1. Populate a `historical_events` table (or a simple CSV) with past indicator values and the observed flood/drought outcome (from disaster records).<br>2. Implement a `compute_confusion_matrix()` worker that iterates the table, compares each value to the approved threshold, and tallies TP/FP/FN/TN.<br>3. Add TEST‑R1; expose the matrix via a new endpoint `GET /api/v1/risk-matrix`. |
| **Cloud‑gap interpolation** | 1. Choose an interpolation method (e.g., inverse‑distance weighting of nearby non‑cloudy pixels).<br>2. Add a column `gap_interpolated BOOLEAN` to `indicator_results` and a column `interpolated_value DOUBLE PRECISION`.<br>3. Populate these columns in the processing pipeline when `quality_flag = CLOUD_CONTAMINATED`.<br>4. Add TEST‑C1 and a UI badge that lights up when `gap_interpolated = true`. |

*All four properties can be **proved** by the automated Gherkin tests listed above *and* by a short live demonstration (run the worker, query the new endpoints, inspect the DB). The demonstrations require only the existing Docker‑Compose setup (or a simple `uv run` of the backend) and a small data set – no production‑level satellite archives are needed.*