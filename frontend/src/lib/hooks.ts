/**
 * TanStack Query hooks for every endpoint the console uses.
 *
 * Query keys are centralised here so invalidation after a mutation is
 * predictable. Mutations invalidate the affected list/collection; nothing is
 * optimistically updated, because the server is the source of truth for
 * audit-logged actions and job state.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { api, apiRequest } from "@/lib/api";
import type {
  AlertActionInput,
  AlertDetail,
  AlertRecord,
  AuditEvent,
  Comparison,
  ComparisonInput,
  ConnectionTest,
  DataSource,
  DataSourceInput,
  Dataset,
  DatasetDetail,
  EvaluateInput,
  EvaluateResult,
  ExportInput,
  ExportJob,
  ForecastInput,
  ForecastValue,
  IndicatorComputeInput,
  IndicatorDefinition,
  IndicatorResult,
  IngestionInput,
  IngestionJob,
  Job,
  Message,
  Page,
  PasswordResetOut,
  ProcessingOperation,
  ProcessingRun,
  ProcessingRunInput,
  Provider,
  PublicAlert,
  PublicDataset,
  PublicMapCollection,
  PublicOverview,
  QualityFlag,
  Report,
  ReportInput,
  Role,
  StudyArea,
  Threshold,
  ThresholdInput,
  ThresholdVersion,
  TimeSeries,
  User,
  UserCreate,
  UserUpdate,
} from "@/lib/types";

export const qk = {
  me: ["me"] as const,
  users: (params?: unknown) => ["admin", "users", params ?? {}] as const,
  roles: ["admin", "roles"] as const,
  permissions: ["admin", "permissions"] as const,
  dataSources: (params?: unknown) => ["admin", "data-sources", params ?? {}] as const,
  dataSource: (id: number) => ["admin", "data-sources", id] as const,
  thresholds: (params?: unknown) => ["admin", "thresholds", params ?? {}] as const,
  threshold: (id: number) => ["admin", "thresholds", id] as const,
  thresholdVersions: (id: number) => ["admin", "thresholds", id, "versions"] as const,
  audit: (params?: unknown) => ["admin", "audit", params ?? {}] as const,
  auditActions: ["admin", "audit", "actions"] as const,
  auditResourceTypes: ["admin", "audit", "resource-types"] as const,
  providers: ["providers"] as const,
  studyAreas: ["study-areas"] as const,
  datasets: (params?: unknown) => ["datasets", params ?? {}] as const,
  dataset: (id: number) => ["datasets", id] as const,
  qualityFlags: ["datasets", "quality-flags"] as const,
  jobs: (params?: unknown) => ["jobs", params ?? {}] as const,
  job: (id: number) => ["jobs", id] as const,
  ingestion: (params?: unknown) => ["ingestion", params ?? {}] as const,
  processingOperations: ["processing", "operations"] as const,
  processingRuns: (params?: unknown) => ["processing", "runs", params ?? {}] as const,
  indicatorDefinitions: ["indicators", "definitions"] as const,
  indicatorResults: (params?: unknown) => ["indicators", "results", params ?? {}] as const,
  timeseries: (params?: unknown) => ["analysis", "timeseries", params ?? {}] as const,
  exports: (params?: unknown) => ["exports", params ?? {}] as const,
  reports: (params?: unknown) => ["reports", params ?? {}] as const,
  alerts: (params?: unknown) => ["disaster", "alerts", params ?? {}] as const,
  alert: (id: number | null) => ["disaster", "alerts", id] as const,
  forecasts: (params?: unknown) => ["disaster", "forecasts", params ?? {}] as const,
};

// ---------------------------------------------------------------- users
export function useUsers(params: { search?: string; page?: number; size?: number; role?: string }) {
  return useQuery({
    queryKey: qk.users(params),
    queryFn: () => api.get<Page<User>>("/admin/users", params),
  });
}

export function useRoles() {
  return useQuery({
    queryKey: qk.roles,
    queryFn: () => api.get<Role[]>("/admin/roles"),
    staleTime: 5 * 60_000,
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: UserCreate) => api.post<User>("/admin/users", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: UserUpdate }) =>
      api.patch<User>(`/admin/users/${id}`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  });
}

export function useSetUserActive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, active }: { id: number; active: boolean }) =>
      api.post<User>(`/admin/users/${id}/${active ? "activate" : "deactivate"}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  });
}

export function useSetUserRoles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, roles }: { id: number; roles: string[] }) =>
      api.put<User>(`/admin/users/${id}/roles`, { roles }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "users"] }),
  });
}

export function useIssuePasswordReset() {
  return useMutation({
    mutationFn: (id: number) => api.post<PasswordResetOut>(`/admin/users/${id}/password-reset`),
  });
}

// ---------------------------------------------------------------- data sources
export function useDataSources(params: {
  search?: string;
  category?: string;
  status?: string;
  page?: number;
  size?: number;
}) {
  return useQuery({
    queryKey: qk.dataSources(params),
    queryFn: () => api.get<Page<DataSource>>("/admin/data-sources", params),
  });
}

export function useDataSource(id: number | null) {
  return useQuery({
    queryKey: qk.dataSource(id ?? 0),
    queryFn: () => api.get<DataSource>(`/admin/data-sources/${id}`),
    enabled: id !== null,
  });
}

export function useCreateDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: DataSourceInput) => api.post<DataSource>("/admin/data-sources", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "data-sources"] }),
  });
}

export function useUpdateDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Partial<DataSourceInput> }) =>
      api.patch<DataSource>(`/admin/data-sources/${id}`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "data-sources"] }),
  });
}

export function useDeleteDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del<void>(`/admin/data-sources/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "data-sources"] }),
  });
}

export function useTestDataSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post<ConnectionTest>(`/admin/data-sources/${id}/test`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "data-sources"] }),
  });
}

// ---------------------------------------------------------------- thresholds
export function useThresholds(params: {
  search?: string;
  category?: string;
  approval_status?: string;
  page?: number;
  size?: number;
}) {
  return useQuery({
    queryKey: qk.thresholds(params),
    queryFn: () => api.get<Page<Threshold>>("/admin/thresholds", params),
  });
}

export function useCreateThreshold() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ThresholdInput) => api.post<Threshold>("/admin/thresholds", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "thresholds"] }),
  });
}

export function useUpdateThreshold() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: ThresholdInput & { change_note?: string } }) =>
      api.patch<Threshold>(`/admin/thresholds/${id}`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "thresholds"] }),
  });
}

export function useDeleteThreshold() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del<void>(`/admin/thresholds/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "thresholds"] }),
  });
}

export function useThresholdVersions(id: number | null) {
  return useQuery({
    queryKey: qk.thresholdVersions(id ?? 0),
    queryFn: () => api.get<ThresholdVersion[]>(`/admin/thresholds/${id}/versions`),
    enabled: id !== null,
  });
}

// ---------------------------------------------------------------- audit
export function useAuditEvents(params: {
  search?: string;
  action?: string;
  actor?: string;
  outcome?: string;
  resource_type?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  size?: number;
}) {
  return useQuery({
    queryKey: qk.audit(params),
    queryFn: () => api.get<Page<AuditEvent>>("/admin/audit", params),
  });
}

export function useAuditActions() {
  return useQuery({
    queryKey: qk.auditActions,
    queryFn: () => api.get<string[]>("/admin/audit/actions"),
    staleTime: 5 * 60_000,
  });
}

export function useAuditResourceTypes() {
  return useQuery({
    queryKey: qk.auditResourceTypes,
    queryFn: () => api.get<string[]>("/admin/audit/resource-types"),
    staleTime: 5 * 60_000,
  });
}

// ---------------------------------------------------------------- providers / study areas
export function useProviders() {
  return useQuery({
    queryKey: qk.providers,
    queryFn: () => api.get<Provider[]>("/providers"),
    staleTime: 5 * 60_000,
  });
}

export function useStudyAreas() {
  return useQuery({
    queryKey: qk.studyAreas,
    queryFn: () => api.get<StudyArea[]>("/study-areas"),
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------- datasets
export function useDatasets(params: {
  search?: string;
  category?: string;
  quality_flag?: string;
  data_source_id?: number;
  study_area_id?: number;
  start_date?: string;
  end_date?: string;
  page?: number;
  size?: number;
}) {
  return useQuery({
    queryKey: qk.datasets(params),
    queryFn: () => api.get<Page<Dataset>>("/datasets", params),
  });
}

export function useDataset(id: number | null) {
  return useQuery({
    queryKey: qk.dataset(id ?? 0),
    queryFn: () => api.get<DatasetDetail>(`/datasets/${id}`),
    enabled: id !== null,
  });
}

export function useQualityFlags() {
  return useQuery({
    queryKey: qk.qualityFlags,
    queryFn: () =>
      api.get<{ flags: QualityFlag[]; descriptions: Record<string, string> }>(
        "/datasets/quality-flags",
      ),
    staleTime: 10 * 60_000,
  });
}

// ---------------------------------------------------------------- jobs
export function useJobs(params: {
  kind?: string;
  status?: string;
  page?: number;
  size?: number;
}) {
  return useQuery({
    queryKey: qk.jobs(params),
    queryFn: () => api.get<Page<Job>>("/jobs", params),
    // Jobs move on their own; poll while any is pending or running.
    refetchInterval: (query) => {
      const data = query.state.data as Page<Job> | undefined;
      const active = data?.items.some((j) => j.status === "pending" || j.status === "running");
      return active ? 3000 : false;
    },
  });
}

export function useJob(id: number | null) {
  return useQuery({
    queryKey: qk.job(id ?? 0),
    queryFn: () => api.get<Job>(`/jobs/${id}`),
    enabled: id !== null,
    refetchInterval: (query) => {
      const job = query.state.data as Job | undefined;
      return job && (job.status === "pending" || job.status === "running") ? 2500 : false;
    },
  });
}

export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post<Job>(`/jobs/${id}/cancel`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

export function useRetryJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post<Job>(`/jobs/${id}/retry`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

// ---------------------------------------------------------------- ingestion
export function useRequestIngestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: IngestionInput) =>
      api.post<IngestionJob>("/ingestion", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ingestion"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useIngestionJobs(params: { page?: number; size?: number; data_source_id?: number }) {
  return useQuery({
    queryKey: qk.ingestion(params),
    queryFn: () => api.get<Page<IngestionJob>>("/ingestion", params),
  });
}

// ---------------------------------------------------------------- processing
export function useProcessingOperations() {
  return useQuery({
    queryKey: qk.processingOperations,
    queryFn: () => api.get<ProcessingOperation[]>("/processing/operations"),
    staleTime: 10 * 60_000,
  });
}

export function useProcessingRuns(params: { page?: number; size?: number; dataset_id?: number }) {
  return useQuery({
    queryKey: qk.processingRuns(params),
    queryFn: () => api.get<Page<ProcessingRun>>("/processing/runs", params),
  });
}

export function useCreateProcessingRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ProcessingRunInput) =>
      api.post<ProcessingRun>("/processing", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["processing", "runs"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

// ---------------------------------------------------------------- indicators
export function useIndicatorDefinitions() {
  return useQuery({
    queryKey: qk.indicatorDefinitions,
    queryFn: () => api.get<IndicatorDefinition[]>("/indicators/definitions"),
    staleTime: 10 * 60_000,
  });
}

export function useIndicatorResults(params: {
  indicator_key?: string;
  study_area_id?: number;
  dataset_id?: number;
  quality_flag?: string;
  start_date?: string;
  end_date?: string;
  page?: number;
  size?: number;
}) {
  return useQuery({
    queryKey: qk.indicatorResults(params),
    queryFn: () => api.get<Page<IndicatorResult>>("/indicators/results", params),
  });
}

export function useComputeIndicators() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: IndicatorComputeInput) => api.post<Job>("/indicators/compute", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["indicators", "results"] });
    },
  });
}

// ---------------------------------------------------------------- analysis
export function useTimeSeries(
  params: {
    indicator_key: string;
    study_area_id?: number;
    dataset_ids?: string;
    start_date?: string;
    end_date?: string;
    aggregation?: string;
  },
  options?: Partial<UseQueryOptions<TimeSeries>>,
) {
  return useQuery({
    queryKey: qk.timeseries(params),
    queryFn: () => api.get<TimeSeries>("/analysis/timeseries", params),
    enabled: Boolean(params.indicator_key),
    ...options,
  });
}

export function useComparePeriods() {
  return useMutation({
    mutationFn: (payload: ComparisonInput) => api.post<Comparison>("/analysis/compare", payload),
  });
}

// ---------------------------------------------------------------- exports
export function useExports(params: { page?: number; size?: number; resource?: string }) {
  return useQuery({
    queryKey: qk.exports(params),
    queryFn: () => api.get<Page<ExportJob>>("/exports", params),
    refetchInterval: (query) => {
      const data = query.state.data as Page<ExportJob> | undefined;
      const active = data?.items.some(
        (e) => e.job && (e.job.status === "pending" || e.job.status === "running"),
      );
      return active ? 3000 : false;
    },
  });
}

export function useCreateExport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ExportInput) => api.post<ExportJob>("/exports", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["exports"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

// ---------------------------------------------------------------- reports
export type ReportListParams = {
  kind?: string;
  status?: string;
  period_type?: string;
  study_area_id?: number;
  page?: number;
  size?: number;
};

export function useReports(params: ReportListParams) {
  return useQuery({
    queryKey: qk.reports(params),
    queryFn: () => api.get<Page<Report>>("/reports", params),
    refetchInterval: (query) => {
      const data = query.state.data as Page<Report> | undefined;
      const active = data?.items.some(
        (r) => r.job_status === "pending" || r.job_status === "running" || r.status === "building",
      );
      return active ? 3000 : false;
    },
  });
}

export function useCreateReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ReportInput) => api.post<Report>("/reports", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

// ---------------------------------------------------------------- public data
/** Public read endpoints need no session: always fetched anonymously. */
export function usePublicOverview() {
  return useQuery({
    queryKey: ["public", "overview"],
    queryFn: () =>
      apiRequest<PublicOverview>("/public/overview", { method: "GET", anonymous: true }),
  });
}

export function usePublicDatasets(params: { page?: number; size?: number }) {
  return useQuery({
    queryKey: ["public", "datasets", params],
    queryFn: () =>
      apiRequest<Page<PublicDataset>>("/public/datasets", { method: "GET", query: params, anonymous: true }),
  });
}

export function usePublicAlerts(params: { severity?: string; kind?: string; page?: number; size?: number }) {
  return useQuery({
    queryKey: ["public", "alerts", params],
    queryFn: () =>
      apiRequest<Page<PublicAlert>>("/public/alerts", { method: "GET", query: params, anonymous: true }),
  });
}

export function usePublicMap() {
  return useQuery({
    queryKey: ["public", "map"],
    queryFn: () => apiRequest<PublicMapCollection>("/public/map", { method: "GET", anonymous: true }),
  });
}

/** Staff-side publish toggles (require the `public.publish` permission). */
export function usePublish(
  resource: "datasets" | "alerts" | "study-areas",
  invalidate?: readonly unknown[],
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, is_public }: { id: number; is_public: boolean }) =>
      apiRequest<unknown>(`/public/${resource}/${id}`, {
        method: "PATCH",
        body: { is_public },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["public"] });
      if (invalidate) qc.invalidateQueries({ queryKey: invalidate });
      qc.invalidateQueries({ queryKey: ["admin", "audit"] });
    },
  });
}

export function useCancelReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.del<void>(`/reports/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

export function useRetryReport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.post<Report>(`/reports/${id}/retry`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["reports"] });
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
}

// ---------------------------------------------------------------- misc
export function useChangePassword() {
  return useMutation({
    mutationFn: (payload: { current_password: string; new_password: string }) =>
      apiRequest<Message>("/auth/change-password", { method: "POST", body: payload }),
  });
}

// ---------------------------------------------------------------- disaster
export function useAlerts(
  params: {
    status?: string;
    severity?: string;
    kind?: string;
    metric_source?: string;
    indicator_key?: string;
    study_area_id?: number;
    page?: number;
    size?: number;
  } = {},
) {
  return useQuery({
    queryKey: qk.alerts(params),
    queryFn: () => api.get<Page<AlertRecord>>("/disaster/alerts", params),
    // open alerts are operational state; poll so the console stays current
    refetchInterval: 15_000,
  });
}

export function useAlert(id: number | null) {
  return useQuery({
    queryKey: qk.alert(id),
    queryFn: () => api.get<AlertDetail>(`/disaster/alerts/${id}`),
    enabled: id != null,
  });
}

export function useAlertAction(action: "acknowledge" | "notes" | "resolve" | "reopen") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: AlertActionInput }) =>
      api.post<AlertDetail>(`/disaster/alerts/${id}/${action}`, payload),
    onSuccess: (detail) => {
      qc.invalidateQueries({ queryKey: ["disaster", "alerts"] });
      qc.invalidateQueries({ queryKey: qk.alert(detail.id) });
      qc.invalidateQueries({ queryKey: ["admin", "audit"] });
    },
  });
}

export function useRunEvaluation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: EvaluateInput) =>
      api.post<EvaluateResult>("/disaster/evaluate", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["disaster", "alerts"] });
      qc.invalidateQueries({ queryKey: ["admin", "audit"] });
    },
  });
}

export function useForecasts(params: {
  indicator_key?: string;
  study_area_id?: number;
  page?: number;
  size?: number;
} = {}) {
  return useQuery({
    queryKey: qk.forecasts(params),
    queryFn: () => api.get<Page<ForecastValue>>("/disaster/forecasts", params),
  });
}

export function useCreateForecast() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ForecastInput) =>
      api.post<ForecastValue>("/disaster/forecasts", payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["disaster", "forecasts"] });
      qc.invalidateQueries({ queryKey: ["admin", "audit"] });
    },
  });
}
