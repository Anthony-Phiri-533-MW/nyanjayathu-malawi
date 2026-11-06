import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Ban,
  Boxes,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Clock3,
  CloudRain,
  Database,
  FileDown,
  FileText,
  Info,
  ListChecks,
  Loader2,
  Minus,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  Users,
  Waves,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAuth } from "@/auth/AuthContext";
import { DashboardAssistantPanel } from "@/components/DashboardAssistantPanel";
import { LakeMapPanel } from "@/components/LakeMapPanel";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ErrorState, EmptyState, LoadingRows } from "@/components/ui/States";
import { cn } from "@/lib/cn";
import { flagStyle, formatDate, formatDateTime, formatNumber, statusStyle, titleCase } from "@/lib/format";
import {
  useDataSources,
  useDatasets,
  useExports,
  useForecasts,
  useJobs,
  usePublicAlerts,
  usePublicMap,
  usePublicOverview,
  usePublicWaterExtents,
  useStudyAreas,
  useThresholds,
  useTimeSeries,
  useUsers,
} from "@/lib/hooks";
import type {
  AlertSeverity,
  AssistantMetric,
  ForecastValue,
  Job,
  JobStatus,
  Page,
  PublicAlert,
  TimeSeries,
  TimeSeriesPoint,
} from "@/lib/types";

/**
 * Staff dashboard.
 *
 * The design follows the shared principles from the dashboard-design
 * literature the team reviewed: one purpose (is the lake okay right now?),
 * a Z-pattern with the decision-driving observation top-left, at most a
 * handful of chunks, context (unit, date, comparison) on every number, and
 * colour used as a signal — never as the only cue.
 *
 * Reading order:
 *   1. Page heading + freshness            → "what am I looking at?"
 *   2. Alert ribbon (only when active)    → "do I need to act now?"
 *   3. Four KPI cards                     → headline status
 *   4. Map + observed trend + alerts      → the explanation
 *   5. Forecasts/activity + workspace     → the next step
 */

type QueryLike<T> = {
  data: T | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
};

type WorkspaceLink = {
  to: string;
  label: string;
  hint: string;
  icon: LucideIcon;
  count?: number;
};

const SEVERITY_BADGE: Record<AlertSeverity, string> = {
  critical: "bg-danger-light text-danger-dark",
  warning: "bg-signal-100 text-signal-700",
  info: "bg-water-50 text-water-800",
};

const SEVERITY_ORDER = ["critical", "warning", "info"] as const;
const SEVERITY_META: Record<(typeof SEVERITY_ORDER)[number], { label: string; dot: string }> = {
  critical: { label: "critical", dot: "bg-danger" },
  warning: { label: "warning", dot: "bg-signal-400" },
  info: { label: "info", dot: "bg-water-500" },
};

const KIND_LABEL: Record<string, string> = {
  flood: "Flood",
  drought: "Drought",
  water_quality: "Water quality",
  general: "General",
};

function shortDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
}

function metricDigits(value: number): number {
  const abs = Math.abs(value);
  if (abs >= 100) return 0;
  if (abs >= 10) return 1;
  return 2;
}

function validPoints(series: TimeSeries | undefined): Array<TimeSeriesPoint & { value: number }> {
  return (series?.points ?? []).filter(
    (point): point is TimeSeriesPoint & { value: number } => point.value !== null,
  );
}

function latestValid(series: TimeSeries | undefined) {
  const points = validPoints(series);
  return points.length ? points[points.length - 1] : undefined;
}

function seriesDelta(series: TimeSeries | undefined): { diff: number } | null {
  const points = validPoints(series);
  if (points.length < 2) return null;
  return { diff: points[points.length - 1].value - points[points.length - 2].value };
}

function sparkPoints(series: TimeSeries | undefined, limit = 12): number[] {
  return validPoints(series)
    .slice(-limit)
    .map((point) => point.value);
}

/* ------------------------------------------------------------------ charts */

/**
 * Dependency-free sparkline. It is decorative only in the sense that the
 * value and delta are always written out next to it, so it never carries
 * meaning on its own.
 */
function Sparkline({
  points,
  className,
  label,
}: {
  points: number[];
  className?: string;
  label: string;
}) {
  if (points.length < 2) return null;

  const width = 160;
  const height = 40;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const flat = max === min;
  const span = max - min || 1;
  const step = width / (points.length - 1);
  const coords = points.map((value, index) => {
    const x = index * step;
    const y = flat ? height / 2 : height - ((value - min) / span) * (height - 6) - 3;
    return [x, y] as const;
  });
  const line = coords
    .map(([x, y], index) => `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
  const area = `${line} L${width} ${height} L0 ${height} Z`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
      className={cn("h-10 w-full", className)}
    >
      <path d={area} fill="currentColor" opacity={0.12} />
      <path
        d={line}
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/* ------------------------------------------------------------- KPI pieces */

function DeltaBadge({
  diff,
  unit,
  featured = false,
}: {
  diff: number;
  unit?: string;
  featured?: boolean;
}) {
  const direction = diff > 0 ? "up" : diff < 0 ? "down" : "flat";
  const Icon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : Minus;
  const word = direction === "up" ? "Up" : direction === "down" ? "Down" : "No change";

  return (
    <span
      className={cn(
        "inline-flex flex-wrap items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        featured ? "bg-white/10 text-water-100" : "bg-water-50 text-water-800",
      )}
    >
      <Icon size={13} aria-hidden />
      <span>
        {direction === "flat"
          ? word
          : `${word} ${formatNumber(Math.abs(diff), {
              digits: metricDigits(Math.abs(diff)),
            })}${unit ? ` ${unit}` : ""}`}
      </span>
      <span className={featured ? "text-water-200" : "text-muted"}>vs previous point</span>
    </span>
  );
}

function SeverityBar({ counts }: { counts: Record<string, number> }) {
  const total = SEVERITY_ORDER.reduce((sum, key) => sum + (counts[key] ?? 0), 0);

  if (!total) {
    return <p className="text-xs text-muted">No open or acknowledged published alerts.</p>;
  }

  return (
    <div>
      <div
        className="flex h-1.5 overflow-hidden rounded-full bg-canvas"
        role="img"
        aria-label={`Active public alerts: ${SEVERITY_ORDER.map(
          (key) => `${counts[key] ?? 0} ${SEVERITY_META[key].label}`,
        ).join(", ")}`}
      >
        {SEVERITY_ORDER.map((key) => {
          const count = counts[key] ?? 0;
          if (!count) return null;
          return (
            <span
              key={key}
              className={cn("h-full", SEVERITY_META[key].dot)}
              style={{ flexGrow: count }}
            />
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
        {SEVERITY_ORDER.map((key) => {
          const count = counts[key] ?? 0;
          if (!count) return null;
          return (
            <span key={key} className="inline-flex items-center gap-1.5">
              <span
                className={cn("h-1.5 w-1.5 rounded-full", SEVERITY_META[key].dot)}
                aria-hidden
              />
              {count} {SEVERITY_META[key].label}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  unit,
  icon: Icon,
  to,
  detail,
  delta,
  spark,
  sparkLabel,
  footer,
  loading = false,
  featured = false,
}: {
  label: string;
  value: React.ReactNode;
  unit?: string;
  icon: LucideIcon;
  to: string;
  detail: React.ReactNode;
  delta?: { diff: number } | null;
  spark?: number[];
  sparkLabel?: string;
  footer?: React.ReactNode;
  loading?: boolean;
  featured?: boolean;
}) {
  return (
    <Link
      to={to}
      className={cn(
        "group flex h-full flex-col rounded-card border p-5 transition-shadow",
        featured
          ? "border-water-800 bg-gradient-to-br from-water-800 via-water-800 to-water-700 text-white shadow-card hover:shadow-pop"
          : "card hover:border-water-200 hover:shadow-pop",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p
          className={cn(
            "text-xs font-medium uppercase tracking-wide",
            featured ? "text-water-200" : "text-muted",
          )}
        >
          {label}
        </p>
        <span
          className={cn(
            "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
            featured ? "bg-white/10 text-water-100" : "bg-water-50 text-water-700",
          )}
        >
          <Icon size={18} aria-hidden />
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-baseline gap-x-2">
        {loading ? (
          <span
            aria-hidden
            className={cn(
              "inline-block h-9 w-28 animate-pulse rounded-md",
              featured ? "bg-white/20" : "bg-canvas",
            )}
          />
        ) : (
          <span
            className={cn(
              "text-3xl font-semibold tracking-tight tabular",
              featured ? "text-white" : "text-ink",
            )}
          >
            {value}
          </span>
        )}
        {!loading && unit ? (
          <span className={cn("text-sm font-medium", featured ? "text-water-200" : "text-muted")}>
            {unit}
          </span>
        ) : null}
      </div>

      <p
        className={cn(
          "mt-1 text-xs leading-relaxed",
          featured ? "text-water-100/90" : "text-muted",
        )}
      >
        {loading ? "Loading published data…" : detail}
      </p>

      {(delta || (spark && spark.length > 1) || footer) && (
        <div className="mt-auto space-y-2 pt-4">
          {delta ? <DeltaBadge diff={delta.diff} unit={unit} featured={featured} /> : null}
          {spark && spark.length > 1 ? (
            <Sparkline
              points={spark}
              label={sparkLabel ?? `${label} recent trend`}
              className={cn("mt-1", featured ? "text-water-200" : "text-water-500")}
            />
          ) : null}
          {footer}
        </div>
      )}
    </Link>
  );
}

/* ------------------------------------------------------------------- cards */

function TrendCard({
  extent,
  level,
  available,
}: {
  extent: QueryLike<TimeSeries>;
  level: QueryLike<TimeSeries>;
  available: boolean;
}) {
  const [kind, setKind] = useState<"extent" | "level">("extent");
  const query = kind === "extent" ? extent : level;
  const points = useMemo(() => validPoints(query.data), [query.data]);
  const latest = points.length ? points[points.length - 1] : undefined;
  const previous = points.length > 1 ? points[points.length - 2] : undefined;
  const chartData = points.map((point) => ({ date: point.date, value: point.value }));
  const unit = query.data?.unit;
  const flag = latest ? flagStyle(latest.quality_flag) : null;

  if (!available) {
    return (
      <Card>
        <CardHeader
          title="Observed trend"
          description="Monthly mean of measured values only."
        />
        <EmptyState
          title="Observed series are not available for your role"
          description="Water extent and water-level series require research indicator access. Published figures remain on the public dashboard."
        />
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Observed trend"
        description={`Monthly mean${unit ? ` · ${unit}` : ""}. Measured values only.`}
        actions={
          <div
            role="group"
            aria-label="Choose observed series"
            className="inline-flex rounded-md border border-border bg-canvas p-0.5"
          >
            <button
              type="button"
              aria-pressed={kind === "extent"}
              onClick={() => setKind("extent")}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                kind === "extent"
                  ? "bg-surface text-water-800 shadow-card"
                  : "text-muted hover:text-ink-soft",
              )}
            >
              Water extent
            </button>
            <button
              type="button"
              aria-pressed={kind === "level"}
              onClick={() => setKind("level")}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                kind === "level"
                  ? "bg-surface text-water-800 shadow-card"
                  : "text-muted hover:text-ink-soft",
              )}
            >
              Water level
            </button>
          </div>
        }
      />

      {query.isLoading ? (
        <LoadingRows rows={3} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={query.refetch} />
      ) : !points.length ? (
        <CardBody>
          <EmptyState
            title={kind === "extent" ? "No water-extent history yet" : "No water-level history yet"}
            description={
              kind === "extent"
                ? "Compute water extent for dated satellite scenes to build this trend."
                : "Satellite altimetry results will appear here once the first water-level observation is computed."
            }
          />
        </CardBody>
      ) : (
        <CardBody>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-3xl font-semibold tracking-tight text-ink tabular">
                {latest ? formatNumber(latest.value, { digits: metricDigits(latest.value) }) : "—"}{" "}
                {unit ? <span className="text-sm font-medium text-muted">{unit}</span> : null}
              </p>
              <p className="mt-1 text-xs text-muted">
                {latest ? `Observed ${formatDate(latest.date)}` : "No observation available"}
                {flag ? ` · ${flag.label}` : ""}
              </p>
            </div>
            {latest && previous ? (
              <DeltaBadge diff={latest.value - previous.value} unit={unit} />
            ) : null}
          </div>

          <div className="mt-4 h-52 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#1d5fa8" stopOpacity={0.22} />
                    <stop offset="100%" stopColor="#1d5fa8" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#e2e5ea" strokeDasharray="3 3" vertical={false} />
                <XAxis
                  dataKey="date"
                  tickFormatter={shortDate}
                  tick={{ fontSize: 10, fill: "#6b7280" }}
                  tickLine={false}
                  axisLine={{ stroke: "#e2e5ea" }}
                  minTickGap={24}
                />
                <YAxis
                  tick={{ fontSize: 10, fill: "#6b7280" }}
                  width={54}
                  tickLine={false}
                  axisLine={false}
                  domain={["auto", "auto"]}
                  tickFormatter={(value: number) => formatNumber(value, { digits: 1 })}
                />
                <Tooltip
                  contentStyle={{
                    fontSize: 12,
                    borderRadius: 8,
                    borderColor: "#e2e5ea",
                    boxShadow: "0 8px 24px rgba(17, 24, 39, 0.12)",
                  }}
                  labelFormatter={(label) => formatDate(String(label))}
                  formatter={(value: number) => [
                    formatNumber(value, { unit }),
                    query.data?.indicator_name ?? "Observation",
                  ]}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  name={query.data?.indicator_name ?? "Observation"}
                  stroke="#1d5fa8"
                  strokeWidth={2}
                  fill="url(#trendFill)"
                  connectNulls={false}
                  activeDot={{ r: 4 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {query.data?.limitations ? (
            <details className="mt-3 text-xs text-muted">
              <summary className="cursor-pointer font-medium text-ink-soft">Method notes</summary>
              <p className="mt-1 leading-relaxed">{query.data.limitations}</p>
            </details>
          ) : null}
        </CardBody>
      )}
    </Card>
  );
}

function PublicAlertsCard({
  alerts,
  isLoading,
  isError,
  onRetry,
}: {
  alerts: PublicAlert[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  return (
    <Card>
      <CardHeader
        title="Public alerts"
        description="Latest alerts published to the open dashboard."
        actions={
          <Link to="/public" className="btn-ghost px-2 py-1 text-xs">
            Public view
            <ArrowUpRight size={13} aria-hidden />
          </Link>
        }
      />

      {isLoading ? (
        <LoadingRows rows={3} />
      ) : isError ? (
        <div className="px-5 py-4">
          <p className="text-sm text-danger-dark">Public alerts could not be loaded.</p>
          <button type="button" className="btn-ghost mt-1 px-2 py-1 text-xs" onClick={onRetry}>
            <RefreshCw size={13} aria-hidden />
            Retry
          </button>
        </div>
      ) : !alerts.length ? (
        <div className="flex items-start gap-3 px-5 py-5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-success-light text-success-dark">
            <CheckCircle2 size={18} aria-hidden />
          </span>
          <div>
            <p className="text-sm font-medium text-ink">No active public alerts</p>
            <p className="mt-0.5 text-xs leading-relaxed text-muted">
              No open or acknowledged alerts are in the public feed. New breaches appear
              automatically after evaluation.
            </p>
          </div>
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {alerts.slice(0, 3).map((alert) => (
            <li key={alert.id} className="px-5 py-3.5">
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={SEVERITY_BADGE[alert.severity] ?? "bg-canvas text-muted"}>
                  {alert.severity}
                </Badge>
                <span className="text-xs font-medium text-ink-soft">
                  {KIND_LABEL[alert.kind] ?? titleCase(alert.kind)}
                </span>
                <span className="ml-auto text-xs text-muted">
                  {formatDateTime(alert.first_seen_at)}
                </span>
              </div>
              <p className="mt-1.5 line-clamp-2 text-sm text-ink">
                {alert.message || `${titleCase(alert.indicator_key)} breach`}
              </p>
              <p className="mt-1 text-xs text-muted">
                {alert.study_area_name ?? "Lake Malawi"} ·{" "}
                {formatNumber(alert.metric_value, { unit: alert.unit })} from{" "}
                {alert.metric_source === "forecast" ? "a recorded forecast" : "computed observations"}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function TabButton({
  selected,
  onClick,
  count,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        "-mb-px inline-flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors",
        selected
          ? "border-water-700 text-water-800"
          : "border-transparent text-muted hover:text-ink-soft",
      )}
    >
      {children}
      {count !== undefined ? (
        <span
          className={cn(
            "rounded-full px-1.5 py-0.5 text-[11px] tabular",
            selected ? "bg-water-50 text-water-800" : "bg-canvas text-muted",
          )}
        >
          {count}
        </span>
      ) : null}
    </button>
  );
}

function jobIcon(status: JobStatus) {
  switch (status) {
    case "succeeded":
      return CheckCircle2;
    case "failed":
      return XCircle;
    case "canceled":
      return Ban;
    case "running":
      return Loader2;
    default:
      return Clock3;
  }
}

function ForecastsAndActivityCard({
  forecasts,
  jobs,
  hasForecastRead,
  canViewForecasts,
  canViewJobs,
}: {
  forecasts: QueryLike<Page<ForecastValue>>;
  jobs: QueryLike<Page<Job>>;
  hasForecastRead: boolean;
  canViewForecasts: boolean;
  canViewJobs: boolean;
}) {
  const [tab, setTab] = useState<"forecasts" | "activity">(
    hasForecastRead ? "forecasts" : "activity",
  );

  const forecastRows = useMemo(() => {
    const all = forecasts.data?.items ?? [];
    const today = new Date().toISOString().slice(0, 10);
    const upcoming = all.filter((forecast) => forecast.target_date >= today);
    return [...(upcoming.length ? upcoming : all)]
      .sort((a, b) => a.target_date.localeCompare(b.target_date))
      .slice(0, 4);
  }, [forecasts.data]);

  const jobRows = (jobs.data?.items ?? []).slice(0, 5);

  return (
    <Card>
      <CardHeader
        title="Forecasts & activity"
        description="Recorded projections and recent platform work, in one place."
        actions={
          tab === "forecasts" && canViewForecasts ? (
            <Link to="/disaster/forecasts" className="btn-ghost px-2 py-1 text-xs">
              All forecasts
              <ChevronRight size={13} aria-hidden />
            </Link>
          ) : canViewJobs ? (
            <Link to="/research/jobs" className="btn-ghost px-2 py-1 text-xs">
              All jobs
              <ChevronRight size={13} aria-hidden />
            </Link>
          ) : null
        }
      />

      <div
        role="group"
        aria-label="Forecasts and platform activity"
        className="flex gap-1 border-b border-border px-3"
      >
        {hasForecastRead ? (
          <TabButton
            selected={tab === "forecasts"}
            onClick={() => setTab("forecasts")}
            count={forecasts.data?.total}
          >
            <CloudRain size={15} aria-hidden />
            Forecasts
          </TabButton>
        ) : null}
        <TabButton
          selected={tab === "activity"}
          onClick={() => setTab("activity")}
          count={jobs.data?.total}
        >
          <ListChecks size={15} aria-hidden />
          Activity
        </TabButton>
      </div>

      {tab === "forecasts" ? (
        <div aria-live="polite">
          {!hasForecastRead ? (
            <EmptyState
              title="Forecast access is not available for this role"
              description="Ask an administrator if you need to review recorded projections."
            />
          ) : forecasts.isLoading ? (
            <LoadingRows rows={4} />
          ) : forecasts.isError ? (
            <ErrorState error={forecasts.error} onRetry={forecasts.refetch} />
          ) : !forecastRows.length ? (
            <EmptyState
              title="No forecasts recorded"
              description="User-supplied projections with a provenance note will appear here."
            />
          ) : (
            <ul className="divide-y divide-border">
              {forecastRows.map((forecast) => (
                <li
                  key={forecast.id}
                  className="flex items-start justify-between gap-4 px-5 py-3"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink">
                      {titleCase(forecast.indicator_key)}
                    </p>
                    <p className="truncate text-xs text-muted">
                      {forecast.study_area_name ?? "Lake Malawi"} · target{" "}
                      {formatDate(forecast.target_date)}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-sm font-semibold text-ink tabular">
                      {formatNumber(forecast.value, { unit: forecast.unit })}
                    </p>
                    <Badge className="mt-1 bg-canvas text-muted">Recorded</Badge>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <div aria-live="polite">
          {!canViewJobs ? (
            <EmptyState
              title="Job activity is not available for this role"
              description="Ask an administrator if you need visibility of platform work."
            />
          ) : jobs.isLoading ? (
            <LoadingRows rows={4} />
          ) : jobs.isError ? (
            <ErrorState error={jobs.error} onRetry={jobs.refetch} />
          ) : !jobRows.length ? (
            <EmptyState
              title="No jobs queued yet"
              description="Ingestion, preprocessing, indicator and export work will appear here."
            />
          ) : (
            <ul className="divide-y divide-border">
              {jobRows.map((job) => {
                const Icon = jobIcon(job.status);
                return (
                  <li key={job.id} className="flex items-center gap-3 px-5 py-3">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-canvas text-ink-soft">
                      <Icon
                        size={15}
                        aria-hidden
                        className={job.status === "running" ? "animate-spin" : undefined}
                      />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-ink">
                        {titleCase(job.kind)} job #{job.id}
                      </p>
                      <p className="truncate text-xs text-muted">
                        {job.message || job.error || "Queued"} · {formatDateTime(job.created_at)}
                      </p>
                    </div>
                    <Badge className={cn("shrink-0", statusStyle(job.status))}>{job.status}</Badge>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

function WorkspaceCard({ links }: { links: WorkspaceLink[] }) {
  return (
    <Card>
      <CardHeader title="Workspace" description="Only the tools your role can access." />
      <CardBody className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
        {links.map((link) => (
          <Link
            key={link.to}
            to={link.to}
            className="group flex items-center gap-3 rounded-lg border border-border px-3 py-2.5 transition-colors hover:border-water-200 hover:bg-water-50/50"
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-water-50 text-water-700">
              <link.icon size={16} aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-ink">{link.label}</span>
              <span className="block truncate text-xs text-muted">{link.hint}</span>
            </span>
            {link.count !== undefined ? (
              <span className="text-sm font-medium text-ink-soft tabular">{link.count}</span>
            ) : null}
            <ChevronRight
              size={15}
              className="shrink-0 text-muted transition-transform group-hover:translate-x-0.5"
              aria-hidden
            />
          </Link>
        ))}
      </CardBody>
    </Card>
  );
}

/* -------------------------------------------------------------------- page */

export function DashboardPage() {
  const { user, can } = useAuth();
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const hasResearchRead = can("research.indicators.read");
  const hasForecastRead = can("disaster.alerts.read");
  const canViewJobs = can("research.datasets.read");
  const alertsHref = hasForecastRead ? "/disaster/alerts" : "/public";
  const seriesHref = hasResearchRead ? "/research/analysis" : "/public";

  const datasets = useDatasets({ page: 1, size: 1 });
  const sources = useDataSources({ page: 1, size: 1 });
  const thresholds = useThresholds({ page: 1, size: 1 });
  const users = useUsers({ page: 1, size: 1 });
  const jobs = useJobs({ page: 1, size: 8 });
  const exports = useExports({ page: 1, size: 1 });

  const overview = usePublicOverview();
  const map = usePublicMap();
  const waterExtents = usePublicWaterExtents({ page: 1, size: 200 });
  const publicAlerts = usePublicAlerts({ page: 1, size: 50 });
  const studyAreas = useStudyAreas(hasResearchRead);
  const defaultArea = studyAreas.data?.find((area) => area.is_default) ?? studyAreas.data?.[0];
  const waterExtentSeries = useTimeSeries(
    { indicator_key: "water_extent", study_area_id: defaultArea?.id, aggregation: "monthly" },
    { enabled: hasResearchRead && Boolean(defaultArea?.id), refetchInterval: 30_000 },
  );
  const waterLevelSeries = useTimeSeries(
    { indicator_key: "water_level_altimetry", study_area_id: defaultArea?.id, aggregation: "monthly" },
    { enabled: hasResearchRead && Boolean(defaultArea?.id), refetchInterval: 30_000 },
  );
  const forecasts = useForecasts({ page: 1, size: 100 }, hasForecastRead);

  const activePublicAlerts = useMemo(
    () => (publicAlerts.data?.items ?? []).filter((alert) => alert.status !== "resolved"),
    [publicAlerts.data],
  );

  const severityCounts = useMemo(
    () =>
      activePublicAlerts.reduce<Record<string, number>>((counts, alert) => {
        counts[alert.severity] = (counts[alert.severity] ?? 0) + 1;
        return counts;
      }, {}),
    [activePublicAlerts],
  );

  const activeAlertCount = overview.data
    ? (overview.data.alerts.by_status.open ?? 0) +
      (overview.data.alerts.by_status.acknowledged ?? 0)
    : activePublicAlerts.length;
  const criticalAlerts = severityCounts.critical ?? 0;

  const latestExtent = latestValid(waterExtentSeries.data);
  const latestLevel = latestValid(waterLevelSeries.data);
  const extentDelta = seriesDelta(waterExtentSeries.data);
  const levelDelta = seriesDelta(waterLevelSeries.data);
  const extentSpark = sparkPoints(waterExtentSeries.data);
  const levelSpark = sparkPoints(waterLevelSeries.data);

  const coverageLabel =
    overview.data?.coverage_start && overview.data?.coverage_end
      ? `${formatDate(overview.data.coverage_start)} – ${formatDate(overview.data.coverage_end)}`
      : "No published coverage yet";

  const assistantMetrics: AssistantMetric[] = [
    {
      label: "Latest mapped water extent",
      value: latestExtent
        ? `${formatNumber(latestExtent.value, { unit: latestExtent.unit })} on ${formatDate(latestExtent.date)}`
        : "No observed value available",
    },
    {
      label: "Latest satellite-derived water level",
      value: latestLevel
        ? `${formatNumber(latestLevel.value, { unit: latestLevel.unit })} on ${formatDate(latestLevel.date)}`
        : "No observed value available",
    },
    {
      label: "Active public alerts",
      value: `${activeAlertCount} open or acknowledged; ${criticalAlerts} critical`,
    },
    {
      label: "Published data",
      value: `${overview.data?.dataset_count ?? 0} datasets across ${
        overview.data?.study_area_count ?? 0
      } study areas`,
    },
    {
      label: "Recorded forecasts",
      value:
        (forecasts.data?.items ?? [])
          .slice(0, 8)
          .map(
            (forecast) =>
              `${titleCase(forecast.indicator_key)} ${formatNumber(forecast.value, {
                unit: forecast.unit,
              })} for ${formatDate(forecast.target_date)}`,
          )
          .join("; ") ||
        (hasForecastRead ? "No forecast values recorded" : "Not available to this role"),
    },
  ];

  const workspaceLinks: WorkspaceLink[] = [
    ...(can("research.datasets.read")
      ? [
          {
            to: "/research/datasets",
            label: "Datasets",
            hint: "Stored and derived data",
            icon: Boxes,
            count: datasets.data?.total,
          },
        ]
      : []),
    ...(can("admin.data_sources.read")
      ? [
          {
            to: "/admin/data-sources",
            label: "Data sources",
            hint: "Provider integrations",
            icon: Database,
            count: sources.data?.total,
          },
        ]
      : []),
    ...(can("admin.thresholds.read")
      ? [
          {
            to: "/admin/thresholds",
            label: "Thresholds",
            hint: "Flagging and alert rules",
            icon: SlidersHorizontal,
            count: thresholds.data?.total,
          },
        ]
      : []),
    ...(can("admin.users.read")
      ? [
          {
            to: "/admin/users",
            label: "Users & roles",
            hint: "Accounts and permissions",
            icon: Users,
            count: users.data?.total,
          },
        ]
      : []),
    ...(can("research.exports.download")
      ? [
          {
            to: "/research/exports",
            label: "Exports",
            hint: "Generated research outputs",
            icon: FileDown,
            count: exports.data?.total,
          },
        ]
      : []),
    ...(can("reports.read")
      ? [
          {
            to: "/reports",
            label: "Reports",
            hint: "Periodic and custom reports",
            icon: FileText,
          },
        ]
      : []),
  ];

  async function refreshAll() {
    if (refreshing) return;
    setRefreshing(true);
    await Promise.allSettled([
      overview.refetch(),
      map.refetch(),
      waterExtents.refetch(),
      publicAlerts.refetch(),
      studyAreas.refetch(),
      waterExtentSeries.refetch(),
      waterLevelSeries.refetch(),
      forecasts.refetch(),
      jobs.refetch(),
    ]);
    setRefreshing(false);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Lake Malawi monitoring"
        title={`Welcome back, ${user?.full_name.split(" ")[0] ?? "researcher"}`}
        description="Your operational view of published lake observations, alerts and recorded forecasts. The map and headline figures refresh automatically."
        meta={
          <>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-success" aria-hidden />
              {overview.data
                ? `Updated ${formatDateTime(overview.data.generated_at)}`
                : "Connecting to published data…"}
            </span>
            <span>Auto-refresh every 30 seconds</span>
            <span className="inline-flex items-center gap-1.5">
              <CalendarDays size={13} aria-hidden />
              {coverageLabel}
            </span>
          </>
        }
        actions={
          <>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => void refreshAll()}
              disabled={refreshing}
              aria-label="Refresh dashboard data"
            >
              <RefreshCw
                size={15}
                aria-hidden
                className={refreshing ? "animate-spin motion-reduce:animate-none" : undefined}
              />
              <span className="hidden sm:inline">{refreshing ? "Refreshing…" : "Refresh"}</span>
            </button>
            <button
              type="button"
              className="btn-secondary"
              aria-expanded={assistantOpen}
              onClick={() => setAssistantOpen((open) => !open)}
            >
              <Sparkles size={16} className="text-water-700" aria-hidden />
              {assistantOpen ? "Close AI panel" : "Explain with AI"}
            </button>
          </>
        }
      />

      {activeAlertCount > 0 ? (
        <div
          role="status"
          aria-live="polite"
          className={cn(
            "flex flex-wrap items-start gap-3 rounded-card border px-4 py-3",
            criticalAlerts
              ? "border-danger/30 bg-danger-light"
              : "border-signal-200 bg-signal-50",
          )}
        >
          <span
            className={cn(
              "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
              criticalAlerts
                ? "bg-danger text-white"
                : "bg-signal-300 text-ink",
            )}
          >
            <AlertTriangle size={15} aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-ink">
              {activeAlertCount} active public alert{activeAlertCount === 1 ? "" : "s"}
            </p>
            <p className="mt-0.5 text-xs leading-relaxed text-ink-soft">
              {criticalAlerts
                ? `${criticalAlerts} at critical severity. Review the response record before the next evaluation.`
                : "Open or acknowledged alerts are visible on the public dashboard. Review the response record to keep it current."}
            </p>
          </div>
          <Link
            to={alertsHref}
            className="btn-secondary shrink-0 px-2.5 py-1.5 text-xs"
          >
            Open alerts
            <ChevronRight size={13} aria-hidden />
          </Link>
        </div>
      ) : null}

      <section aria-label="Lake status at a glance" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          featured
          label="Mapped water extent"
          value={
            latestExtent
              ? formatNumber(latestExtent.value, { digits: metricDigits(latestExtent.value) })
              : "—"
          }
          unit={latestExtent?.unit}
          icon={Waves}
          to={seriesHref}
          loading={hasResearchRead && waterExtentSeries.isLoading}
          detail={
            latestExtent
              ? `Observed ${formatDate(latestExtent.date)} · ${flagStyle(latestExtent.quality_flag).label}`
              : hasResearchRead
                ? "No computed observation yet. Compute water extent from a dated scene to start the record."
                : "Not available for your role. Published figures remain on the public dashboard."
          }
          delta={extentDelta}
          spark={extentSpark}
          sparkLabel="Recent mapped water extent observations"
        />

        <MetricCard
          label="Water level"
          value={
            latestLevel
              ? formatNumber(latestLevel.value, { digits: metricDigits(latestLevel.value) })
              : "—"
          }
          unit={latestLevel?.unit}
          icon={Activity}
          to={seriesHref}
          loading={hasResearchRead && waterLevelSeries.isLoading}
          detail={
            latestLevel
              ? `Observed ${formatDate(latestLevel.date)} · Satellite altimetry · ${
                  flagStyle(latestLevel.quality_flag).label
                }`
              : hasResearchRead
                ? "No altimetry observation yet. Water extent is an area, not a level."
                : "Not available for your role. Published figures remain on the public dashboard."
          }
          delta={levelDelta}
          spark={levelSpark}
          sparkLabel="Recent satellite-derived water level observations"
        />

        <MetricCard
          label="Active public alerts"
          value={String(activeAlertCount)}
          icon={AlertTriangle}
          to={alertsHref}
          loading={overview.isLoading && publicAlerts.isLoading}
          detail={
            activeAlertCount
              ? "Open or acknowledged alerts published to the public dashboard."
              : "No open or acknowledged published alerts."
          }
          footer={<SeverityBar counts={severityCounts} />}
        />

        <MetricCard
          label="Published datasets"
          value={overview.data ? String(overview.data.dataset_count) : "—"}
          icon={Database}
          to="/public"
          loading={overview.isLoading}
          detail={
            overview.data
              ? `${overview.data.study_area_count} public study area${
                  overview.data.study_area_count === 1 ? "" : "s"
                } · metadata only`
              : "Published data only"
          }
          footer={
            <div className="rounded-md border border-border bg-canvas/70 px-3 py-2">
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted">
                Coverage
              </p>
              <p className="mt-0.5 text-xs text-ink-soft">{coverageLabel}</p>
            </div>
          }
        />
      </section>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(20rem,1fr)]">
        <LakeMapPanel
          mapData={map.data}
          waterExtents={waterExtents.data?.items ?? []}
          isLoading={map.isLoading}
          isTimelineLoading={waterExtents.isLoading}
          mapError={map.error}
          timelineError={waterExtents.error}
          onRetry={() => {
            void map.refetch();
            void waterExtents.refetch();
          }}
        />

        <div className="space-y-5">
          <TrendCard
            extent={waterExtentSeries}
            level={waterLevelSeries}
            available={hasResearchRead}
          />
          <PublicAlertsCard
            alerts={activePublicAlerts}
            isLoading={publicAlerts.isLoading}
            isError={publicAlerts.isError}
            onRetry={() => void publicAlerts.refetch()}
          />
        </div>
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(20rem,1fr)]">
        <ForecastsAndActivityCard
          forecasts={forecasts}
          jobs={jobs}
          hasForecastRead={hasForecastRead}
          canViewForecasts={hasForecastRead}
          canViewJobs={canViewJobs}
        />
        <WorkspaceCard links={workspaceLinks} />
      </div>

      <footer className="space-y-1 border-t border-border pt-4 text-xs leading-relaxed text-muted">
        <p className="flex items-start gap-1.5">
          <Info size={13} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            Water extent is a mapped area, not a water level. Forecasts are staff-recorded
            projections, not model output. Proxy-derived values are labelled unvalidated.
          </span>
        </p>
        {overview.data?.provenance ? <p>{overview.data.provenance}</p> : null}
      </footer>

      {assistantOpen ? (
        <DashboardAssistantPanel
          metrics={assistantMetrics}
          onClose={() => setAssistantOpen(false)}
        />
      ) : null}
    </div>
  );
}
