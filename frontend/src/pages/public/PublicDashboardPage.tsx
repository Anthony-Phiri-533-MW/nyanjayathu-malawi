import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { LakeMapPanel } from "@/components/LakeMapPanel";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import {
  usePublicAlerts,
  usePublicDatasets,
  usePublicMap,
  usePublicOverview,
  usePublicWaterExtents,
} from "@/lib/hooks";
import { formatBytes, formatDate, formatDateTime, formatNumber, titleCase } from "@/lib/format";
import type { AlertSeverity } from "@/lib/types";

/**
 * Public Data Module — the one screen anyone can see without signing in.
 *
 * It consumes only the anonymous `/api/v1/public/*` endpoints, which expose
 * rows a staff member has explicitly published. The heading styling, cards,
 * badges and tables reuse the same design system as the staff console so the
 * two sides read as one product; the difference is that nothing here carries
 * an action — it is strictly read-only.
 */

/** Same semantic palette the staff console uses for alerts. */
const SEVERITY_STYLE: Record<AlertSeverity, string> = {
  critical: "bg-danger-light text-danger-dark border border-danger/30",
  warning: "bg-signal-100 text-signal-700 border border-signal-200",
  info: "bg-canvas text-muted border border-border",
};

const STATUS_STYLE: Record<string, string> = {
  open: "bg-water-50 text-water-800 border border-water-200",
  acknowledged: "bg-info-light text-info-dark border border-info/30",
  resolved: "bg-success-light text-success-dark border border-success/30",
};

const KIND_STYLE: Record<string, string> = {
  flood: "bg-water-50 text-water-800",
  drought: "bg-signal-100 text-signal-700",
  water_quality: "bg-info-light text-info-dark",
  general: "bg-canvas text-muted",
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardBody>
        <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
        <p className="mt-1 text-2xl font-semibold text-ink">{value}</p>
        {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
      </CardBody>
    </Card>
  );
}

export function PublicDashboardPage() {
  const overview = usePublicOverview();
  const datasets = usePublicDatasets({ page: 1, size: 50 });
  const alerts = usePublicAlerts({ page: 1, size: 50 });
  const map = usePublicMap();
  const waterExtents = usePublicWaterExtents({ page: 1, size: 200 });

  const activeSeverityTotals = useMemo(() => {
    const out: Record<string, number> = {};
    for (const alert of alerts.data?.items ?? []) {
      if (alert.status === "resolved") continue;
      out[alert.severity] = (out[alert.severity] ?? 0) + 1;
    }
    return out;
  }, [alerts.data]);

  return (
    <div className="min-h-screen bg-canvas">
      {/* Public header — same product identity, no account chrome. */}
      <header className="border-b border-border bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Link to="/public" className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-md bg-water-700 text-base font-semibold text-white">
              LW
            </span>
            <div className="leading-tight">
              <p className="text-lg font-semibold text-ink">LakeWatch Public</p>
              <p className="text-sm text-muted">Lake Malawi monitoring — open data</p>
            </div>
          </Link>
          <Link
            to="/login"
            className="text-sm text-water-700 underline-offset-4 hover:underline"
          >
            Staff sign in
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-5 px-4 py-6 sm:px-6">
        <div>
          <h1 className="text-xl font-semibold text-ink">Public dashboard</h1>
          <p className="mt-1 text-sm text-muted">
            Published datasets, published study areas and disaster alerts for Lake Malawi.
            Everything on this page is read-only and needs no account.
          </p>
        </div>

        {overview.isError ? (
          <ErrorState error={overview.error} onRetry={() => overview.refetch()} />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              label="Published datasets"
              value={overview.data ? String(overview.data.dataset_count) : "—"}
              hint="Approved records the team has made public"
            />
            <Stat
              label="Public study areas"
              value={overview.data ? String(overview.data.study_area_count) : "—"}
              hint="Shown on the map below"
            />
            <Stat
              label="Active public alerts"
              value={
                overview.data
                  ? String(
                      (overview.data.alerts.by_status.open ?? 0) +
                        (overview.data.alerts.by_status.acknowledged ?? 0),
                    )
                  : "—"
              }
              hint="Open or acknowledged (not resolved)"
            />
            <Stat
              label="Data coverage"
              value={
                overview.data?.coverage_start
                  ? `${formatDate(overview.data.coverage_start)} → ${formatDate(overview.data.coverage_end)}`
                  : "—"
              }
              hint="Span of published dataset periods"
            />
          </div>
        )}

        {overview.data?.alerts.by_severity.critical ? (
          <div className="rounded-md border border-danger/30 bg-danger-light px-4 py-3 text-sm text-danger-dark">
            {overview.data.alerts.by_severity.critical} active published alert(s) are at
            critical severity.
          </div>
        ) : null}

        <LakeMapPanel
          mapData={map.data}
          waterExtents={waterExtents.data?.items ?? []}
          isLoading={map.isLoading}
          mapError={map.error}
          timelineError={waterExtents.error}
          onRetry={() => {
            void map.refetch();
            void waterExtents.refetch();
          }}
        />

        {/* Published alerts */}
        <Card>
          <CardHeader
            title="Disaster alerts"
            description={`${overview.data?.alerts.total ?? 0} published alert(s). ${Object.entries(activeSeverityTotals)
              .filter(([s]) => s !== "info")
              .map(([s, n]) => `${n} ${s}`)
              .join(", ") || "none"} active.`}
          />
          {alerts.isLoading ? (
            <LoadingRows rows={4} />
          ) : alerts.isError ? (
            <ErrorState error={alerts.error} onRetry={() => alerts.refetch()} />
          ) : alerts.data && alerts.data.items.length > 0 ? (
            <ul className="divide-y divide-border">
              {alerts.data.items.map((alert) => (
                <li key={alert.id} className="px-5 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge className={SEVERITY_STYLE[alert.severity]}>{alert.severity}</Badge>
                      <Badge className={STATUS_STYLE[alert.status] ?? "bg-canvas text-muted"}>{alert.status}</Badge>
                      <Badge className={KIND_STYLE[alert.kind] ?? "bg-canvas text-muted"}>{titleCase(alert.kind)}</Badge>
                    </div>
                    <span className="text-xs text-muted">first seen {formatDateTime(alert.first_seen_at)}</span>
                  </div>
                  <p className="mt-2 text-sm text-ink">
                    {alert.message ? alert.message : `${titleCase(alert.indicator_key)} breach`}
                  </p>
                  <p className="mt-1 text-xs text-muted">
                    {alert.indicator_name || titleCase(alert.indicator_key)} ·{" "}
                    {formatNumber(alert.metric_value, { unit: alert.unit })} from{" "}
                    {alert.metric_source === "forecast" ? "a recorded forecast" : "computed observations"} ·
                    seen {alert.times_seen}×
                    {alert.study_area_name ? ` · ${alert.study_area_name}` : ""}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No public alerts"
              description="Alerts appear here only after the team publishes them."
            />
          )}
        </Card>

        {/* Published datasets */}
        <Card>
          <CardHeader
            title="Published datasets"
            description="Metadata only — raw files stay in the team's internal store."
          />
          {datasets.isLoading ? (
            <LoadingRows rows={5} />
          ) : datasets.isError ? (
            <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
          ) : datasets.data && datasets.data.items.length > 0 ? (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>Dataset</Th>
                    <Th>Type</Th>
                    <Th>Period</Th>
                    <Th>Quality</Th>
                    <Th align="right">Size</Th>
                  </tr>
                </thead>
                <tbody>
                  {datasets.data.items.map((dataset) => {
                    const unvalidated = dataset.quality_flag === "UNVALIDATED";
                    return (
                      <Tr key={dataset.id}>
                        <Td>
                          <p className="font-medium text-ink">{dataset.title}</p>
                          <p className="text-xs text-muted">
                            {dataset.provider_key}
                            {dataset.resolution_m ? ` · ${dataset.resolution_m} m resolution` : ""}
                          </p>
                        </Td>
                        <Td>
                          <Badge className="bg-canvas text-muted">
                            {dataset.is_raw ? "Observed" : "Derived"} · {dataset.format ?? titleCase(dataset.kind)}
                          </Badge>
                        </Td>
                        <Td className="whitespace-nowrap text-xs">
                          {formatDate(dataset.start_date)} → {formatDate(dataset.end_date)}
                        </Td>
                        <Td>
                          <Badge
                            className={
                              unvalidated ? "bg-signal-100 text-signal-700" : "bg-success-light text-success-dark"
                            }
                          >
                            {unvalidated ? "Unvalidated (proxy/indicative)" : dataset.quality_flag}
                          </Badge>
                        </Td>
                        <Td align="right">{formatBytes(dataset.size_bytes)}</Td>
                      </Tr>
                    );
                  })}
                </tbody>
              </Table>
              <Pagination
                page={datasets.data.page}
                pages={datasets.data.pages}
                total={datasets.data.total}
                onChange={() => undefined}
              />
            </>
          ) : (
            <EmptyState
              title="No published datasets"
              description="Dataset metadata appears here once the team publishes it."
            />
          )}
        </Card>

        <p className="pb-6 text-xs text-muted">{overview.data?.provenance}</p>
      </main>
    </div>
  );
}
