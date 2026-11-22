# Software Requirements Specification (SRS) – LakeWatch

**Version:** 0.1  
**Date:** 2026‑11‑24  

This document lists the functional requirements for the LakeWatch platform.  
Each requirement is tagged **Built (B)**, **Partial (P)** or **New (N)**.

| # | Requirement (brief) | Tag |
|---|----------------------|-----|
| FR‑01 | System shall ingest CHIRPS daily rainfall rasters and store them as `Dataset` records. | B |
| FR‑02 | System shall ingest Sentinel‑2 L2A mosaics and compute MNDWI/NDWI water‑extent indicators. | B |
| FR‑03 | System shall ingest MODIS LST and produce `surface_water_temperature` indicator values. | B |
| FR‑04 | System shall ingest NASA POWER meteorological data and derive `rainfall_summary` and `temperature_summary`. | B |
| FR‑05 | System shall persist every indicator result with **unit**, **sensor**, **date**, and **processing version**. | B |
| FR‑06 | UI shall display water‑extent km² with a **Provisional** badge when the default threshold 0.0 is used. | B |
| FR‑07 | Disaster‑alert engine shall compare latest indicator values against **approved** thresholds and emit alerts. | B |
| FR‑08 | Public dashboard shall show only datasets/alerts where `is_public = true`. | B |
| FR‑09 | API shall reject ingestion jobs that exceed `max_dim` = 2048 pixels without windowed cutting. | B |
| FR‑10 | Backend shall log every threshold change in an append‑only `audit_log` table. | B |
| FR‑11 | AI‑interpret‑metrics endpoint shall strip raw geometry before forwarding to the LLM. | P |
| FR‑12 | Report generation shall freeze a snapshot of all indicator statistics at build time. | B |
| FR‑13 | System shall allow a **super‑admin** to grant/revoke any permission. | B |
| FR‑14 | Frontend shall enforce **role‑based hiding** of UI controls (e.g., `public.publish` button visible only to admin). | B |
| FR‑15 | System shall provide a **REST** endpoint `GET /public/overview` that returns lake‑wide summary stats. | N |
| FR‑16 | Ingestion pipeline shall record **SHA‑256** checksum of every downloaded bundle. | N |
| FR‑17 | System shall support **multiple study areas** (default Lake Malawi + user‑defined polygons). | N |
| FR‑18 *(Signature)* | Every stored indicator value must carry **metre (m)** or **square‑kilometre (km²)** unit; unit‑mismatch must be caught by unit tests. | N |
| FR‑19 *(Signature)* | Flood / drought risk classification must be derived from **documented threshold tables** and never from ad‑hoc constants. | N |
| FR‑20 *(Signature)* | Cloud‑masked scenes must be explicitly flagged; gap‑filled values must be labelled “interpolated” and never presented as raw observations. | N |
| FR‑21 | System shall expose a `GET /health` liveness probe that also reports “data‑source status”. | B |
| FR‑22 | Backend shall run a **daily scheduler** that triggers indicator recomputation for the previous 24 h. | P |
| FR‑23 | Frontend map shall be constrained to `maxBounds` of Malawi and initial view centred on Lake Malawi. | B |
| FR‑24 | System shall allow **versioned threshold** configurations; each alert snapshots the threshold version at breach time. | B |

*Tags explanation* – **Built (B)**: already implemented and tested; **Partial (P)**: present but needs polishing/full coverage; **New (N)**: not yet implemented, to be addressed in the remaining work.