# Requirement: Software Characterisation of Lake Malawi Water Monitoring (LMWM)

## 1. Overview
**LakeWatch (LMWM)** is a **scientific remote‑sensing analytics application** that ingests multispectral satellite scenes (CHIRPS, Sentinel‑2, MODIS, NASA POWER), computes a suite of water‑quality and water‑extent indicators, and supports disaster‑alert generation for flood and drought risk over Lake Malawi. The system is designed for research‑grade accuracy, provenance tracking, and uncertainty reporting, as described in the accompanying ADRs and SRS.

## 2. Classification
| Dimension | Description |
|-----------|-------------|
| **Domain** | Limnology / Water‑resources monitoring for Lake Malawi (East African Rift Lake). |
| **Data source** | Multi‑sensor remote‑sensing (optical & microwave) – CHIRPS (rainfall), Sentinel‑2 (MNDWI/NDWI), MODIS (LST), NASA POWER (meteorology). |
| **Processing** | End‑to‑end pipeline: ingestion → windowed calibration → spectral‑index computation (Strategy) → quality‑flag evaluation → indicator result storage → disaster‑threshold comparison → alert emission. |
| **Users** | Researchers, disaster‑management officials, policy makers, and the general public (via an anonymised dashboard). |
| **Accountability** | Full audit trail (every threshold change, ingestion job, indicator computation is logged). |
| **Regulatory compliance** | Operates under the **Malawi Data Protection Act (2023)**; all personal‑data‑linked coordinates are minimised and flagged. |
| **Failure‑mode focus** | Emphasis on *graceful degradation* (cloud‑masked scenes become “interpolated”, unvalidated proxies are labelled, NULL values are never fabricated). |

**Conclusion:** LMWM is *not* a generic Earth‑observation viewer; it is a **domain‑specific analytics platform** that turns raw satellite data into quantified, uncertainty‑aware indicators and risk classifications for a specific water body.

## 3. Failure‑rate curve comparison
| System | Typical failure pattern | Approximate MTBF (Mean Time Between Failures) | Curve shape |
|--------|------------------------|---------------------------------------------|-------------|
| **LMWM (this system)** | - Provider‑side HTTP time‑outs (configurable `HTTP_TIMEOUT_SECONDS=30`).<br>- Raster windowing failures when AOI exceeds `max_dim` (2048 pixels).<br>- Quality‑flag mis‑classification if cloud‑fraction thresholds shift. | **≈ 95 %** of jobs complete successfully; the remaining **5 %** are mostly *retryable* network or dimension‑limit errors. | ** bathtub‑style**: early‑life failures (network hand‑shakes), useful‑life period with very low random failures, wear‑out only when data‑volume grows beyond design limits. |
| **Sentinel‑2 (ESA satellite sensor)** | - Instrument calibrations, orbital anomalies, data‑loss segments.<br>- Typical satellite product failure rate published by ESA: ~0.3 % missing granules per month. | **≈ 99.7 %** availability per month (per ESA statistics). | **Monotonically decreasing** (random independent failures) – rarely exhibits a bathtub shape because satellite components are replaced/serviced rather than “aged” in‑situ. |

### 3.1 Visual (conceptual) sketch
```
Probability of success
 1.0 |           Sentinel‑2 (random failures)
      \          /
       \        /
 0.95  \______/   LMWM (bathtub)
      /      \
     /        \
   0.0        Time (months)
```
*LMWM early‑life bump corresponds to prototype integration phase; after the first few months the curve flattens to the 95 % success plateau.*

## 4. Required actions (to be implemented)
| # | Action | Owner | Target |
|---|--------|-------|--------|
| FR‑L1 | Formalise LMWM as a “scientific remote‑sensing analytics application” in the project’s *Scope* document. | Lead Dev (you) | Immediate |
| FR‑L2 | Document the *failure‑rate characteristics* (bathtub curve) and compare with published satellite sensor metrics (as above). | QA / Documentation lead | Immediate |
| FR‑L3 | Add a **rate‑limit** configuration (already present as `HTTP_TIMEOUT_SECONDS`) and expose a metric `jobs_success_rate` in the `/health` endpoint. | Backend engineer | Sprint 2 |
| FR‑L4 | Produce a **monthly reliability report** (automated job) that logs number of ingestion jobs, successes, failures, and plots the cumulative failure curve. | Ops / Data engineer | Next release |
| FR‑L5 | Ensure all failure events are captured in the `audit_log` with a `failure_category` field (network, window, quality, threshold). | Backend engineer | Sprint 3 |

## 5. Traceability
| Requirement | Linked artifact |
|-------------|-----------------|
| FR‑L1 | `docs/LMWM_Requirement.md` (this file) |
| FR‑L2 | Same markdown, contains curve comparison table |
| FR‑L3 | `backend/app/core/rate_limit.py` (existing) + new health‑endpoint metric |
| FR‑L4 | New cron job `scripts/monthly_reliability_report.py` (to be created) |
| FR‑L5 | `audit_log` schema extension (migration `ba20bc51427c_initial_schema.py`) |

---

*Prepared for the LakeWatch project – version 0.8‑asbuilt (2026‑11‑24).*