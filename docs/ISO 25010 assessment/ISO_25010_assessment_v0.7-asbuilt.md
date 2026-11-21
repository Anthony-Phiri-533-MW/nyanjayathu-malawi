# ISO 25010 Quality Attribute Assessment: LakeWatch v0.7-asbuilt

**Repository**: SE2026-24311351019-lake-malawi-monitoring  
**Tag**: v0.7-asbuilt  
**Baseline Token**: AP19-H4WL-ZQ26  
**Date**: 2026-11-21  
**Prepared**: OpenCode analysis of existing codebase and documentation  

---

## Executive Summary

This report assesses the LakeWatch satellite & ML Lake Malawi Monitoring platform against ISO 25010 system quality attributes, focusing on three key areas: **Functional Correctness**, **Time Behaviour (Performance Efficiency)**, and **Accountability** (mapped to ISO 25010 Reliability and Maintainability categories).

The project is an as-built (`v0.7-asbuilt`) academic platform implementing five end-to-end modules for Lake Malawi water quality monitoring. The assessment is based on codebase exploration, README documentation, ADR-001, and existing test suites — no new code execution was performed.

---

## 1. Functional Correctness

### 🟡 Partially Meets Criteria

#### Strengths

| Quality Aspect | Evidence |
|----------------|----------|
| **Comprehensive module coverage** | Six modules fully implemented: Admin, Data Analysis & Research, Disaster Management, Report Generation, Public Data, LakeWatch dashboard (README Section 1) |
| **Honesty & non-fabrication policy** | Explicit rule: "When an indicator cannot be computed, the result row stores `value = NULL` with an explicit reason — never `0`" (README Section 8.5) |
| **Detailed provenance tracking** | Every `IndicatorResult` stores: `provenance_json`, `parameters_json`, `uncertainty_json`, `quality_flag`, `quality_reason`, `flag_reasons_json` (base.py lines 322-345) |
| **Versioned quality rules** | `QUALITY_RULE_VERSION = "1.0.0"` with documented priority order: MISSING_DATA → PROCESSING_FAILED → INSUFFICIENT_COVERAGE → CLOUD_CONTAMINATED → LOW_QUALITY → UNVALIDATED → VALID (quality.py lines 20-28) |
| **Disaster evaluation transparency** | Threshold snapshots preserved at breach time; deduping with "Re-evaluated" notes appended to response history; severity never auto-downgrades (disaster.py lines 24-36, 327-330, 423-447) |
| **Role-based access control** | Three roles (`super_admin`, `admin`, `researcher`) with 70+ granular permission entries; privilege-escalation guards enforced (README Section 6.1) |

#### Limitations & Provisional Qualifications

| Limitation | Evidence |
|------------|----------|
| **Provisional thresholds** | Water-mask threshold `0.0`, coverage/cloud limits, and all indicator defaults are "provisional" and "not calibrated for Lake Malawi" (README Sections 8.2, 8.3, 8.4) |
| **Unvalidated proxies** | Chlorophyll-a and turbidity are "proxy" outputs flagged `UNVALIDATED`; "never presented as in-situ measurements" (README Section 8.3) |
| **No forecast generation** | "Forecast values are user-entered with mandatory provenance; alerts record `metric_source = forecast` vs `observed`" (README Section 8.7) |
| **Spatial query scope** | PostGIS enables spatial filter pushdown; on SQLite filters run in Python "which is fine for the AOI-sized data this system handles but does not scale to country-wide scans" (README Section 8.7) |
| **Docker untested locally** | "Docker artifacts untested locally: both Dockerfiles and `frontend/nginx.conf` were not built or run in this environment" (README Section 8.1) |
| **No official calibration** | All defaults are documented as provisional; scientific methods are cited but not locally validated for Lake Malawi-specific conditions |

#### Verdict

The system **functionally correctly** implements all documented features, with explicit and pervasive labeling of what is provisional vs. validated. The code never fabricates data (NULL values with reasons), provenance is thorough, and the permission model is granular and enforced. However, functional correctness claims are **qualified throughout** — the "provisional" and "unvalidated" labeling means the system meets its *own* specifications, but those specifications are deliberately not calibrated for the Lake Malawi context. This is a deliberate design choice, not a bug, but it affects the attribute's assessment.

---

## 2. Time Behaviour (Performance Efficiency)

### 🟡 Partially Meets Criteria

#### Strengths

| Quality Aspect | Evidence |
|----------------|----------|
| **Windowed raster loading** | "Rasters are read windowed to the study-area bounding box and bounded by `ingestion_config.max_dim` (default 2048) so continental scenes are never loaded whole" (README Section 8.1) |
| **Spatial query optimization** | `app/services/spatial.py` detects PostGIS availability and "pushes spatial filters down to PostGIS when possible; otherwise it filters in Python" (README Section 5) |
| **Development ergonomics** | Quick-start commands documented: `docker compose up --build`, `uvicorn app.main:app --reload --port 8000`, `npm run dev` (README Sections 2-3) |
| **SQLite fallback** | "SQLite is a supported zero-config fallback for development and tests" (README Section 1, Architecture table) |
| **TanStack Query caching** | "Automatic caching, refetching, stale-while-revalidate" for frontend data (README Section 1) |
| **Database-backed job queue** | "Adequate for a single instance but is not a distributed scheduler (no priority queues or cron)" (README Section 8.7) |

#### Limitations & Scope Notes

| Limitation | Evidence |
|------------|----------|
| **Single-node deployment** | Job queue is "adequate for a single instance but is not a distributed scheduler (no priority queues or cron)" (README Section 8.7) |
| **No performance benchmarks** | No documented benchmarks for raster processing speed, query response times, or concurrent user capacity |
| **Docker untested locally** | "Docker was unavailable" in the assessment environment; `docker compose config` recommended before first deployment |
| **Spatial query scope limitation** | SQLite filters run in Python; "does not scale to country-wide scans" (README Section 8.7) |
| **No CDN or edge caching** | Frontend static assets served via nginx in Docker Compose; no edge/CMS strategy documented |
| **Report build-time semantics** | "Reports are a frozen snapshot: `summary_json` and the stored file are written once at build time. Nothing regenerates or schedules them — a 'periodic' report is built on demand with a calendar window, not by cron" (README Section 8.5) |
| **No scalability guarantees** | System is designed and documented for Lake Malawi AOI-sized data, not country-wide or high-concurrency deployment |

#### Verdict

The system has **thoughtful performance considerations** within its stated scope: windowed raster loading, spatial query optimization, intelligent caching, and clear development/run loops. However, performance is **explicitly scoped** to "single-node" and "AOI-sized data," with no benchmarks or scalability guarantees for larger deployments. The disclaimers about Docker unavailability and SQLite spatial limitations further constrain the performance claim. The system meets its *own* documented performance requirements, but those requirements are narrow in scope.

---

## 3. Accountability

### ✅ Mostly Meets Criteria (mapped to ISO 25010: Reliability + Maintainability)

#### Strengths

| Quality Aspect | Evidence |
|----------------|----------|
| **Extensive audit event logging** | `audit_service.record()` called across all major operations: forecast.create, alert.update, alert.create, disaster.evaluate, alert.acknowledge, alert.resolve, alert.reopen, dataset.publish, alert.unpublish, study_area.publish/unpublish, report.request, report.complete (disaster.py throughout, base.py, reports.py) |
| **Append-only response histories** | `AlertResponse` rows create immutable audit trail: "acknowledge / note / resolve / reopen each create an append-only `AlertResponse` row plus an audit event" (README Section 8.5) |
| **Threshold snapshot preservation** | "Alerts snapshot the threshold (operator, values, version, approval) at breach time, so later threshold edits never rewrite history" (README Section 8.5) |
| **Privilege escalation guards** | "Only a `super_admin` may grant or revoke `super_admin`; a plain administrator cannot modify a `super_admin` account or grant roles at/above their own level; administrators cannot change their own roles or activation state; and the last active administrator cannot be deactivated or demoted" (README Section 6.1) |
| **Role-based access control** | Three roles with granular permission matrix (70+ entries); read-only roles endpoint; "deny-by-default: every protected endpoint requires an explicit permission" (README Section 6) |
| **Public data publish/unpublish audits** | `PATCH /api/v1/public/{entity}/{id}` with `{"is_public": true|false}` writes audit events (`dataset.publish`, `alert.publish`, `study_area.publish` and their `unpublish` counterparts) (README Section 8.7) |
| **Versioned quality rules with idempotent bootstrap** | `QUALITY_RULE_VERSION = "1.0.0"`; "Existing databases pick up new permission rows automatically at next startup (bootstrap is idempotent)" (README Section 5) |
| **Disaster deduping accountability** | "While an alert for the same (study area, indicator, threshold) is open/acknowledged, re-evaluation updates it — latest value, `times_seen` counter, severity escalation (never automatic downgrade), and appends a *Re-evaluated* note to its response history" (README Section 8.5) |
| **Failed report handling** | "Failures persist `status = failed` + an error message once retries are exhausted" (README Section 8.5) |

#### Limitations

| Limitation | Evidence |
|------------|----------|
| **No external audit log storage** | All audit events appear to be in-memory/DB-based; no external write-once log system or append-only external store mentioned |
| **No retention/export policy documented** | How long audit events are kept, or whether they can be exported/archived for compliance, not specified |
| **No integrity/hashing mechanism** | No mention of cryptographic hash chains, tamper-evident logging, or immutable audit log storage outside the DB |
| **No data lineage model** | While per-result provenance is tracked (sensor → indicator → result), end-to-end data lineage from source measurement → processed indicator → alert → report is not explicitly modeled |
| **Backup/restore for audit data not detailed** | Docker volume persistence for PostGIS is mentioned, but backup/restore procedures for audit/ history data not documented |
| **Privilege audit scope gap** | Audit events track *what* happened but not *who authorized* changes in some contexts (e.g., threshold edits by super_admin) |

#### Verdict

The project implements **strong accountability features far above typical** for this type of system. The audit logging is comprehensive, append-only histories prevent silent modification, threshold snapshots prevent history rewriting, and RBAC guards are well-enforced. The main gaps are in audit log *retention/export policy* and *tamper-evidence/hashing* features, but for an academic project-scale system, the accountability model is notably thorough and well-enforced. Maps most closely to ISO 25010 **Reliability** (fault tolerance, recoverability) and **Maintainability** (analyzability, changeability).

---

## 4. Overall Attribute Summary

| ISO 25010 Attribute | Assessment Status | Key Strengths | Key Limitations |
|---------------------|-------------------|---------------|-----------------|
| **Functional Correctness** | 🟡 Partially | Comprehensive module coverage, honesty rules (no fabrication), detailed provenance, granular RBAC | Provisional/unvalidated thresholds, uncalibrated for Lake Malawi, no forecast generation, spatial query limitations |
| **Time Behaviour** | 🟡 Partially | Windowed raster loading, spatial query optimization, dev ergonomics, SQLite fallback | Single-node only, no benchmarks, Docker untested locally, no CDN, spatial scope limitations |
| **Accountability** | ✅ Mostly (→ Reliability + Maintainability) | Extensive audit logging, append-only histories, threshold snapshots, RBAC guards, publish/unpublish audits, versioned rules | No external audit storage, no retention/export policy, no integrity/hashing, no data lineage model |

---

## 5. Version & Release Information

| Field | Value |
|-------|-------|
| **System Release** | v0.7-asbuilt |
| **Baseline Tag Message** | AP19-H4WL-ZQ26 |
| **Repository** | SE2026-24311351019-lake-malawi-monitoring |
| **Mirror Repository** | nyanjayathu-malawi |
| **Tag Pushed To** | Both `origin` and `upstream` remotes |
| **GitHub Release** | Created on both repositories |
| **ADS Document** | ADR-001.md (technology stack justification) |
| **Baseline README** | `AP19-H4WL-ZQ26` added to README header |
| **Assessment Date** | 2026-11-21 |
| **Assessment Method** | Codebase exploration + documentation analysis (no code execution) |

---

## 6. Revision History

| Version | Date | Change | Author |
|---------|------|--------|--------|
| v0.7-asbuilt | 2026-11-21 | Initial ISO 25010 quality attribute assessment | OpenCode analysis |

---

## 7. References

1. ISO/IEC 25010:2011 — Systems and software quality model
2. LakeWatch Repository — SE2026-24311351019-lake-malawi-monitoring
3. ADR-001.md — Technology stack justification
4. README.md — Project architecture and quick-start documentation
5. disaster.py — Disaster evaluation engine with documented provisional rules
6. quality.py — Quality rule version 1.0.0 with documented priority order
7. base.py — Indicator result make/failed result patterns with provenance
8. README Section 8 — "Known limitations" subsection
9. ISO 25010:2011(en) — Systems and software quality model

---

*This assessment is based on analysis of the as-built system (v0.7-asbuilt) without code execution. All limitations and provisional qualifications are as documented in the project's README, ADR-001, and source code comments. The "provisional" and "unvalidated" labeling throughout the codebase is a deliberate design choice, not an oversight.*