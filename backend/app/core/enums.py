"""Shared string-literal enumerations.

Stored as plain strings in the database for cross-dialect portability
(PostgreSQL and SQLite) and enforced through Pydantic at the API boundary.
"""
from __future__ import annotations

from typing import Literal

# --- data sources -----------------------------------------------------------
DataSourceCategory = Literal[
    "sentinel2",
    "landsat",
    "modis",
    "satellite_rainfall",
    "satellite_temperature",
    "satellite_altimetry",
]
DATA_SOURCE_CATEGORIES: list[tuple[str, str]] = [
    ("sentinel2", "Sentinel-2 (optical imagery)"),
    ("landsat", "Landsat (optical imagery)"),
    ("modis", "MODIS (optical & land products)"),
    ("satellite_rainfall", "Satellite rainfall products"),
    ("satellite_temperature", "Satellite temperature products"),
    ("satellite_altimetry", "Satellite altimetry / water-level datasets"),
]

AuthMethod = Literal["none", "api_key", "bearer_token", "basic", "earthdata_token"]
AUTH_METHODS: list[tuple[str, str]] = [
    ("none", "No authentication (public data)"),
    ("api_key", "API key (referenced secret)"),
    ("bearer_token", "Bearer token (referenced secret)"),
    ("basic", "HTTP basic auth (referenced secret)"),
    ("earthdata_token", "NASA Earthdata bearer token (referenced secret)"),
]

# configured -> known but never tested; testing -> test in progress;
# verified -> last connection test succeeded; failed -> last test/request failed.
SourceStatus = Literal["configured", "testing", "verified", "failed"]

# --- thresholds -------------------------------------------------------------
ThresholdOperator = Literal["gt", "gte", "lt", "lte", "between"]
THRESHOLD_OPERATORS: list[tuple[str, str]] = [
    (">", "gt"),
    (">=", "gte"),
    ("<", "lt"),
    ("<=", "lte"),
    ("between", "between"),
]
ThresholdApprovalStatus = Literal["provisional", "pending_review", "approved"]

# --- jobs -------------------------------------------------------------------
JobKind = Literal["ingestion", "processing", "indicator", "export"]
JobStatus = Literal["pending", "running", "succeeded", "failed", "canceled"]

# --- research ---------------------------------------------------------------
QualityFlag = Literal[
    "VALID",
    "LOW_QUALITY",
    "INSUFFICIENT_COVERAGE",
    "CLOUD_CONTAMINATED",
    "MISSING_DATA",
    "PROCESSING_FAILED",
    "UNVALIDATED",
]
QUALITY_FLAGS: list[str] = [
    "VALID",
    "LOW_QUALITY",
    "INSUFFICIENT_COVERAGE",
    "CLOUD_CONTAMINATED",
    "MISSING_DATA",
    "PROCESSING_FAILED",
    "UNVALIDATED",
]

DatasetKind = Literal["observed", "composite", "processed"]
DatasetCategory = DataSourceCategory
IndicatorCategory = Literal["water_level", "water_quality", "climate"]
ExportFormat = Literal["csv", "json", "geojson", "geotiff"]
ExportResource = Literal["datasets", "indicator_results", "timeseries", "comparison", "raster"]
QualitySubject = Literal["dataset", "product", "indicator_result"]
AuditOutcome = Literal["success", "failure"]

# --- disaster management -------------------------------------------------------
# kind: the hazard class of the alert (flood|drought|water_quality|general).
# severity: escalation of a breach (derived from exceedance magnitude; the
# mapping defaults are provisional and documented in the README).
# metric_source: what was compared - a computed indicator value ("observed")
# or a manually recorded forecast value ("forecast").
AlertKind = Literal["flood", "drought", "water_quality", "general"]
ALERT_KINDS: list[tuple[str, str]] = [
    ("flood", "High water / inundation risk"),
    ("drought", "Water shortage / drying conditions"),
    ("water_quality", "Water-quality hazard (e.g. algal bloom proxies)"),
    ("general", "Threshold breach (no specific hazard class)"),
]
AlertSeverity = Literal["info", "warning", "critical"]
ALERT_SEVERITIES: list[tuple[str, str]] = [
    ("info", "Informational breach"),
    ("warning", "Action advised"),
    ("critical", "Urgent response required"),
]
AlertStatus = Literal["open", "acknowledged", "resolved"]
ALERT_STATUSES: list[tuple[str, str]] = [
    ("open", "Not yet acknowledged"),
    ("acknowledged", "Seen by a user; response in progress"),
    ("resolved", "Response record closed"),
]
AlertMetricSource = Literal["observed", "forecast"]
AlertResponseType = Literal["acknowledged", "note", "resolved", "reopened"]

# --- report generation ----------------------------------------------------------
ReportKind = Literal["periodic", "custom"]
REPORT_KINDS: list[tuple[str, str]] = [
    ("periodic", "Recurring period window (derived from period_type)"),
    ("custom", "Explicit period chosen by the user"),
]
ReportPeriodType = Literal["daily", "weekly", "monthly", "quarterly", "annual"]
REPORT_PERIOD_TYPES: list[tuple[str, str]] = [
    ("daily", "Today"),
    ("weekly", "Last 7 days including today"),
    ("monthly", "This calendar month so far"),
    ("quarterly", "This calendar quarter so far"),
    ("annual", "This calendar year so far"),
]
ReportFormat = Literal["pdf", "csv"]
ReportStatus = Literal["queued", "building", "completed", "failed"]
REPORT_STATUSES: list[tuple[str, str]] = [
    ("queued", "Waiting for a worker to build the report"),
    ("building", "Being generated"),
    ("completed", "File stored and ready for download"),
    ("failed", "Generation failed; see the error message"),
]
