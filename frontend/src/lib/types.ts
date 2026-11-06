/**
 * API contract types.
 *
 * These mirror the Pydantic schemas in `backend/app/schemas/` (admin.py,
 * research.py, common.py).  Keep them in sync when the API changes; the field
 * names are intentionally identical so responses can be used directly.
 */

// ---------------------------------------------------------------- common
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
}

export interface Message {
  message: string;
}

// ---------------------------------------------------------------- auth / users
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in_minutes: number;
}

export interface User {
  id: number;
  email: string;
  full_name: string;
  department: string | null;
  is_active: boolean;
  roles: string[];
  permissions: string[];
  created_at: string;
  updated_at: string | null;
  last_login_at: string | null;
  created_by_id: number | null;
}

export interface Role {
  id: number;
  name: string;
  description: string;
  permissions: string[];
}

export interface UserCreate {
  email: string;
  full_name: string;
  password: string;
  roles: string[];
  department?: string | null;
  is_active?: boolean;
}

export interface UserUpdate {
  full_name?: string;
  department?: string | null;
  password?: string;
  is_active?: boolean;
  roles?: string[];
}

export interface PasswordResetOut {
  user_id: number;
  reset_token: string;
  expires_at: string;
}

// ---------------------------------------------------------------- data sources
export interface DataSource {
  id: number;
  name: string;
  provider_key: string;
  category: string;
  dataset_name: string;
  dataset_identifier: string;
  description: string;
  is_enabled: boolean;
  coverage_geojson: Record<string, unknown> | null;
  temporal_start: string | null;
  temporal_end: string | null;
  variables: Array<Record<string, unknown>> | Record<string, unknown> | null;
  ingestion_config: Record<string, unknown> | null;
  auth_method: string;
  credential_ref: string | null;
  status: string;
  last_test_at: string | null;
  last_test_status: string | null;
  last_test_message: string | null;
  last_ingestion_attempt_at: string | null;
  last_success_at: string | null;
  error_status: string | null;
  error_detail: string | null;
  dataset_count: number;
  created_at: string;
  updated_at: string | null;
}

export interface DataSourceInput {
  name: string;
  provider_key: string;
  category: string;
  dataset_name?: string;
  dataset_identifier?: string;
  description?: string;
  is_enabled?: boolean;
  temporal_start?: string | null;
  temporal_end?: string | null;
  variables?: Array<Record<string, unknown>>;
  ingestion_config?: Record<string, unknown>;
  auth_method?: string;
  credential_ref?: string | null;
}

export interface ConnectionTest {
  source_id: number;
  status: string;
  tested_at: string;
  message: string;
  latency_ms: number | null;
  details: Record<string, unknown>;
}

// ---------------------------------------------------------------- thresholds
export type ThresholdOperator = "gt" | "gte" | "lt" | "lte" | "between";
export type ApprovalStatus = "provisional" | "pending_review" | "approved";

export interface Threshold {
  id: number;
  indicator_key: string;
  indicator_name: string;
  unit: string;
  operator: ThresholdOperator;
  value_low: number | null;
  value_high: number | null;
  description: string;
  justification: string;
  reference: string;
  approval_status: ApprovalStatus;
  effective_from: string | null;
  effective_to: string | null;
  is_enabled: boolean;
  version: number;
  created_at: string;
  updated_at: string | null;
  /** True for provisional/unvalidated configurations - surfaced in the UI. */
  is_provisional: boolean;
}

export interface ThresholdVersion {
  id: number;
  version: number;
  change_note: string;
  changed_by_email: string | null;
  created_at: string;
  snapshot: Record<string, unknown> | null;
}

export interface ThresholdInput {
  indicator_key: string;
  indicator_name: string;
  unit: string;
  operator: ThresholdOperator;
  value_low?: number | null;
  value_high?: number | null;
  description?: string;
  justification?: string;
  reference?: string;
  approval_status?: ApprovalStatus;
  effective_from?: string | null;
  effective_to?: string | null;
  is_enabled?: boolean;
}

// ---------------------------------------------------------------- audit
export interface AuditEvent {
  id: number;
  created_at: string;
  actor_id: number | null;
  actor_email: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  outcome: string;
  ip_address: string | null;
  request_id: string | null;
  message: string;
  details: Record<string, unknown> | null;
}

// ---------------------------------------------------------------- study areas
export interface StudyArea {
  id: number;
  name: string;
  description: string;
  boundary_geojson: GeoJSONGeometry;
  minx: number;
  miny: number;
  maxx: number;
  maxy: number;
  is_default: boolean;
  is_public: boolean;
}

export type GeoJSONGeometry = {
  type: string;
  coordinates?: unknown;
  [key: string]: unknown;
};

// ---------------------------------------------------------------- providers
export interface Provider {
  key: string;
  label: string;
  category: string;
  description: string;
  product_type: string;
  verification_note: string;
  auth_method: string;
  auth_required: boolean;
  variables: Array<Record<string, unknown>>;
  capabilities: Record<string, unknown>;
  adapter_status: string;
}

// ---------------------------------------------------------------- datasets
export type QualityFlag =
  | "VALID"
  | "LOW_QUALITY"
  | "INSUFFICIENT_COVERAGE"
  | "CLOUD_CONTAMINATED"
  | "MISSING_DATA"
  | "PROCESSING_FAILED"
  | "UNVALIDATED";

export interface Band {
  key: string;
  label: string;
  unit: string;
  scale: number;
  offset: number;
  wavelength_nm: number | null;
  description: string;
}

export interface QualityAssessment {
  id: number;
  subject_type: string;
  subject_id: number;
  rule_version: string;
  flag: QualityFlag;
  reason: string;
  coverage_fraction: number | null;
  missing_fraction: number | null;
  cloud_fraction: number | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface Dataset {
  id: number;
  title: string;
  provider_key: string;
  category: string;
  product_type: string;
  kind: string;
  is_raw: boolean;
  is_public: boolean;
  data_source_id: number | null;
  data_source_name: string | null;
  ingestion_job_id: number | null;
  study_area_id: number | null;
  study_area_name: string | null;
  start_date: string | null;
  end_date: string | null;
  crs: string | null;
  resolution_m: number | null;
  bands: Band[];
  coverage_geojson: GeoJSONGeometry | null;
  format: string | null;
  size_bytes: number | null;
  quality_flag: QualityFlag;
  quality_reason: string;
  coverage_fraction: number | null;
  created_at: string;
}

export interface BandStatistic {
  count: number;
  min: number | null;
  max: number | null;
  mean: number | null;
  median?: number | null;
  std?: number | null;
  valid_fraction?: number | null;
}

export interface DatasetDetail extends Dataset {
  metadata: Record<string, unknown> | null;
  provenance: Record<string, unknown> | null;
  checksum: string | null;
  quality_assessments: QualityAssessment[];
  indicator_result_count: number;
  band_statistics: Record<string, BandStatistic> | null;
}

// ---------------------------------------------------------------- jobs
export type JobStatus = "pending" | "running" | "succeeded" | "failed" | "canceled";

export interface Job {
  id: number;
  kind: string;
  status: JobStatus;
  progress: number;
  message: string;
  params: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error: string | null;
  attempts: number;
  requested_by_id: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface IngestionJob {
  id: number;
  job_id: number;
  data_source_id: number;
  data_source_name: string | null;
  study_area_id: number;
  study_area_name: string | null;
  start_date: string;
  end_date: string;
  variables: unknown;
  discovered_count: number;
  stored_count: number;
  created_at: string;
  job: Job | null;
}

// ---------------------------------------------------------------- processing
export interface ProcessingParamSpec {
  name: string;
  type: string;
  default: unknown;
  description: string;
}

export interface ProcessingOperation {
  key: string;
  label: string;
  description: string;
  params: ProcessingParamSpec[];
  writes_product: boolean;
  requires: string[];
}

export interface ProcessingRun {
  id: number;
  operation: string;
  params: Record<string, unknown> | null;
  algorithm_version: string;
  input_dataset_ids: number[] | null;
  job_id: number | null;
  status: string;
  metrics: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  products: Array<Record<string, unknown>>;
}

export interface ProcessingRunInput {
  dataset_ids: number[];
  operations: string[];
  params?: Record<string, unknown>;
  output_name?: string;
}

// ---------------------------------------------------------------- indicators
export type IndicatorCategory = string;

export interface IndicatorDefinition {
  id: number;
  key: string;
  name: string;
  category: IndicatorCategory;
  description: string;
  definition: string;
  unit: string;
  method: string;
  method_version: string;
  is_proxy: boolean;
  is_enabled: boolean;
  params: Record<string, unknown> | null;
}

export interface IndicatorResult {
  id: number;
  definition_id: number;
  indicator_key: string;
  study_area_id: number | null;
  study_area_name: string | null;
  dataset_id: number | null;
  dataset_title: string | null;
  product_id: number | null;
  job_id: number | null;
  value: number | null;
  unit: string;
  observed_start: string;
  observed_end: string;
  temporal_resolution: string;
  spatial_resolution: string;
  quality_flag: QualityFlag;
  quality_reason: string;
  spatial_extent_geojson: GeoJSONGeometry | null;
  flag_reasons: unknown;
  coverage_fraction: number | null;
  missing_fraction: number | null;
  uncertainty: Record<string, unknown> | null;
  provenance: Record<string, unknown> | null;
  parameters: Record<string, unknown> | null;
  created_at: string;
}

export interface IndicatorComputeInput {
  indicator_keys: string[];
  study_area_id?: number | null;
  dataset_ids?: number[] | null;
  start_date?: string | null;
  end_date?: string | null;
}

// ---------------------------------------------------------------- timeseries / comparison
export interface TimeSeriesPoint {
  date: string;
  value: number | null;
  unit: string;
  quality_flag: QualityFlag;
  quality_reason: string;
  result_id: number | null;
  dataset_id: number | null;
  dataset_title: string | null;
  coverage_fraction: number | null;
}

export interface TimeSeries {
  indicator_key: string;
  indicator_name: string;
  unit: string;
  study_area_id: number | null;
  aggregation: string;
  date_from: string | null;
  date_to: string | null;
  points: TimeSeriesPoint[];
  excluded_points: number;
  limitations: string;
}

export interface PeriodWindow {
  start: string;
  end: string;
}

export interface ComparisonSide {
  period: PeriodWindow;
  value: number | null;
  unit: string;
  quality_flag: QualityFlag;
  quality_reason: string;
  sample_count: number;
  excluded_count: number;
  points: TimeSeriesPoint[];
}

export interface ComparisonEntry {
  indicator_key: string;
  indicator_name: string;
  unit: string;
  aggregation: string;
  a: ComparisonSide;
  b: ComparisonSide;
  delta: number | null;
  delta_percent: number | null;
  compatible: boolean;
  notes: string;
}

export interface Comparison {
  study_area_id: number;
  study_area_name: string;
  aggregation: string;
  entries: ComparisonEntry[];
  limitations: string;
}

export interface ComparisonInput {
  study_area_id: number;
  indicator_keys: string[];
  period_a: PeriodWindow;
  period_b: PeriodWindow;
  dataset_ids?: number[] | null;
  aggregation?: string;
}

// ---------------------------------------------------------------- exports
export type ExportResource =
  | "datasets"
  | "indicator_results"
  | "timeseries"
  | "comparison"
  | "raster";
export type ExportFormat = "csv" | "json" | "geojson" | "geotiff";

export interface ExportJob {
  id: number;
  job_id: number;
  format: ExportFormat;
  resource_type: ExportResource;
  params: Record<string, unknown> | null;
  file_name: string | null;
  size_bytes: number | null;
  created_by_id: number | null;
  created_at: string;
  job: Job | null;
  download_url: string | null;
}

export interface ExportInput {
  resource: ExportResource;
  format: ExportFormat;
  filters?: Record<string, unknown>;
  options?: Record<string, unknown>;
}

// ---------------------------------------------------------------- reports
export type ReportKind = "periodic" | "custom";
export type ReportPeriodType = "daily" | "weekly" | "monthly" | "quarterly" | "annual";
export type ReportFormat = "pdf" | "csv";
export type ReportSection = "overview" | "indicators" | "forecasts" | "alerts";

export interface Report {
  id: number;
  job_id: number;
  title: string;
  kind: ReportKind;
  period_type: ReportPeriodType | null;
  period_start: string;
  period_end: string;
  study_area_id: number | null;
  study_area_name: string | null;
  format: ReportFormat;
  status: "queued" | "building" | "completed" | "failed" | "canceled";
  error: string | null;
  file_name: string | null;
  size_bytes: number | null;
  download_url: string | null;
  created_by_email: string | null;
  created_at: string;
  completed_at: string | null;
  job_status: string | null;
}

export interface ReportDetail extends Report {
  summary_json: Record<string, unknown> | null;
}

export interface ReportInput {
  title?: string;
  kind: ReportKind;
  period_type?: ReportPeriodType;
  period_start?: string;
  period_end?: string;
  format: ReportFormat;
  study_area_id?: number;
  indicator_keys?: string[];
  include_sections?: ReportSection[];
  note?: string;
}

// ---------------------------------------------------------------- public data
/** Read-only views of published rows (minimum-necessary fields only). */
export interface PublicDataset {
  id: number;
  title: string;
  provider_key: string;
  category: string;
  product_type: string;
  kind: string;
  is_raw: boolean;
  start_date: string | null;
  end_date: string | null;
  crs: string | null;
  resolution_m: number | null;
  format: string | null;
  size_bytes: number | null;
  quality_flag: string;
  quality_reason: string;
  coverage_fraction: number | null;
  study_area_id: number | null;
  study_area_name: string | null;
  created_at: string;
}

export interface PublicAlert {
  id: number;
  kind: string;
  severity: AlertSeverity;
  status: string;
  message: string;
  indicator_key: string;
  indicator_name: string;
  metric_source: string;
  metric_value: number;
  metric_date: string | null;
  unit: string;
  times_seen: number;
  first_seen_at: string;
  last_evaluated_at: string;
  study_area_id: number | null;
  study_area_name: string | null;
}

export interface PublicOverview {
  generated_at: string;
  dataset_count: number;
  study_area_count: number;
  coverage_start: string | null;
  coverage_end: string | null;
  alerts: {
    total: number;
    by_severity: Record<string, number>;
    by_kind: Record<string, number>;
    by_status: Record<string, number>;
  };
  provenance: string;
}

export interface PublicMapFeature {
  type: "Feature";
  id: number;
  properties: {
    id: number;
    name: string;
    description: string;
    is_default: boolean;
    public_dataset_count: number;
    active_public_alerts: number;
    by_severity: Record<string, number>;
    highest_active_severity: string | null;
  };
  geometry: unknown;
}

export interface PublicMapCollection {
  type: "FeatureCollection";
  features: PublicMapFeature[];
  dataset_coverages: PublicDatasetCoverage[];
  indicator_observations?: PublicIndicatorObservation[];
  generated_at: string;
  provenance: string;
}

export interface PublicIndicatorObservation {
  type: "Feature";
  id: number;
  geometry: GeoJSONGeometry;
  properties: {
    id: number;
    indicator_key: string;
    indicator_name: string;
    category: string;
    is_proxy: boolean;
    value: number;
    unit: string;
    observed_start: string;
    observed_end: string;
    quality_flag: string;
    study_area_id: number | null;
    dataset_title: string;
  };
}

export interface PublicDatasetCoverage {
  type: "Feature";
  id: number;
  geometry: GeoJSONGeometry;
  properties: {
    id: number;
    title: string;
    is_raw: boolean;
    quality_flag: string;
    start_date: string | null;
    end_date: string | null;
  };
}

export interface PublicWaterExtent {
  id: number;
  dataset_id: number;
  dataset_title: string;
  observed_start: string;
  observed_end: string;
  value: number;
  unit: string;
  quality_flag: string;
  spatial_extent_geojson: GeoJSONGeometry;
}

export interface AssistantMetric {
  label: string;
  value: string;
}

export interface AssistantInterpretRequest {
  question: string;
  metrics: AssistantMetric[];
}

export interface AssistantInterpretResponse {
  answer: string;
}

// ---------------------------------------------------------------- ingestion
export interface IngestionInput {
  data_source_id: number;
  study_area_id: number;
  start_date: string;
  end_date: string;
  variables?: string[];
}

// ---------------------------------------------------------------- disaster
export type AlertKind = "flood" | "drought" | "water_quality" | "general";
export type AlertSeverity = "info" | "warning" | "critical";
export type AlertStatus = "open" | "acknowledged" | "resolved";
export type AlertMetricSource = "observed" | "forecast";

export interface ForecastValue {
  id: number;
  study_area_id: number;
  study_area_name: string | null;
  indicator_key: string;
  target_date: string;
  value: number;
  unit: string;
  note: string;
  source: "manual" | "model";
  model_id: number | null;
  model_name: string | null;
  model_algorithm: string | null;
  run_id: number | null;
  lead_time_days: number;
  lower: number | null;
  upper: number | null;
  issued_at: string | null;
  created_at: string;
  created_by_email: string | null;
}

export type ForecastInput = {
  indicator_key: string;
  study_area_id: number;
  target_date: string;
  value: number;
  unit: string;
  note: string;
};

// ---------------------------------------------------------------- ML forecasting (research API: /api/v1/forecasts/*)
export interface MLModel {
  id: number;
  key: string;
  name: string;
  algorithm: string;
  version: string;
  indicator_key: string;
  study_area_id: number | null;
  study_area_name: string | null;
  cadence: string;
  n_lags: number;
  feature_names: unknown;
  params: Record<string, unknown> | null;
  train_start: string | null;
  train_end: string | null;
  n_train: number;
  metrics: Record<string, unknown> | null;
  rmse: number | null;
  mae: number | null;
  bias: number | null;
  skill_score: number | null;
  artifact_sha256: string | null;
  is_active: boolean;
  trained_at: string;
}

export interface ModelEvaluation {
  id: number;
  model_id: number;
  indicator_key: string;
  study_area_id: number | null;
  fold: number;
  horizon_days: number;
  train_start: string | null;
  train_end: string | null;
  test_start: string | null;
  test_end: string | null;
  n_train: number;
  n_test: number;
  rmse: number | null;
  mae: number | null;
  bias: number | null;
  mape: number | null;
  r2: number | null;
  skill_score: number | null;
  coverage: number | null;
  metrics: Record<string, unknown> | null;
}

export interface ForecastRun {
  id: number;
  study_area_id: number;
  study_area_name: string | null;
  indicator_key: string;
  model_id: number | null;
  status: string;
  horizon_days: number;
  issued_at: string;
  finished_at: string | null;
  row_count: number;
  message: string;
  metrics: Record<string, unknown> | null;
}

export interface LocalModelFeature {
  key: string;
  label: string;
  unit: string;
}

export interface LocalModel {
  key: string;
  name: string;
  target: string;
  unit: string;
  features: LocalModelFeature[];
  metrics: Record<string, number> | null;
  metrics_note: string;
  ready: boolean;
  unavailable_reason: string | null;
}

export interface LocalModelPrediction {
  model_key: string;
  model_name: string;
  target: string;
  unit: string;
  value: number;
  features: Record<string, number>;
}

export interface AlertRecord {
  id: number;
  study_area_id: number | null;
  study_area_name: string | null;
  indicator_key: string;
  indicator_name: string;
  threshold_id: number | null;
  threshold_snapshot: {
    operator: string;
    value_low: number | null;
    value_high: number | null;
    approval_status: string;
    version: number;
    reference: string;
  } | null;
  metric_source: AlertMetricSource;
  metric_value: number;
  metric_date: string | null;
  unit: string;
  kind: AlertKind;
  severity: AlertSeverity;
  status: AlertStatus;
  is_public: boolean;
  message: string;
  first_seen_at: string;
  last_evaluated_at: string;
  times_seen: number;
  acknowledged_at: string | null;
  acknowledged_by_email: string | null;
  resolved_at: string | null;
  resolved_by_email: string | null;
  created_at: string;
}

export interface AlertResponse {
  id: number;
  response_type: "acknowledged" | "note" | "resolved" | "reopened";
  note: string;
  actor_email: string | null;
  created_at: string;
}

export interface AlertDetail extends AlertRecord {
  responses: AlertResponse[];
}

export type AlertActionInput = {
  note?: string;
  severity?: AlertSeverity | null;
  kind?: AlertKind | null;
};

export type EvaluateInput = {
  study_area_ids?: number[];
  indicator_keys?: string[];
  include_provisional?: boolean;
  dry_run?: boolean;
};

export interface EvaluateMatch {
  study_area_id: number;
  study_area_name: string | null;
  indicator_key: string;
  threshold_id: number | null;
  metric_source: AlertMetricSource;
  metric_value: number | null;
  metric_date: string | null;
  breached: boolean | null;
  severity: AlertSeverity | null;
  alert_id: number | null;
  skipped_reason: string | null;
}

export interface EvaluateResult {
  dry_run: boolean;
  include_provisional: boolean;
  thresholds_used: number;
  pairs_considered: number;
  pairs_skipped: number;
  breached: number;
  alerts_created: number;
  alerts_updated: number;
  matches: EvaluateMatch[];
}
