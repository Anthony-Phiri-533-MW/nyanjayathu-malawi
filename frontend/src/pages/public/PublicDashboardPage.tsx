import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { LakeMapPanel } from "@/components/LakeMapPanel";
import { DashboardAssistantPanel } from "@/components/DashboardAssistantPanel";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { MapPin, AlertTriangle, Database, Clock, Waves } from "lucide-react";
import {
  usePublicAlerts,
  usePublicDatasets,
  usePublicMap,
  usePublicOverview,
  usePublicWaterExtents,
} from "@/lib/hooks";
import { formatBytes, formatDate, formatDateTime, titleCase } from "@/lib/format";

/**
 * Public Data Module — the one screen anyone can see without signing in.
 *
 * It consumes only the anonymous `/api/v1/public/*` endpoints, which expose
 * rows a staff member has explicitly published. The heading styling, cards,
 * badges and tables reuse the same design system as the staff console so the
 * two sides read as one product; the difference is that nothing here carries
 * an action — it is strictly read-only.
 */

const STATUS_STYLE: Record<string, string> = {
  open: "bg-water-50 text-water-800 border border-water-200",
  acknowledged: "bg-info-light text-info-dark border border-info/30",
  resolved: "bg-success-light text-success-dark border border-success/30",
};

const STAT_ICONS: Record<string, { icon: React.ElementType; color: string }> = {
  "Published datasets": { icon: Database, color: "text-water-700" },
  "Public study areas": { icon: MapPin, color: "text-water-600" },
  "Active public alerts": { icon: AlertTriangle, color: "text-danger-600" },
  "Data coverage": { icon: Clock, color: "text-signal-600" },
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  const { icon: Icon, color } = STAT_ICONS[label] ?? { icon: Waves, color: "text-water-600" };
  return (
    <Card className="group hover:border-water-200 transition-colors">
      <CardBody className="px-5 py-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
            <p className="mt-1 text-3xl font-semibold text-ink tabular-nums">{value}</p>
            {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
          </div>
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-canvas text-ink-soft group-hover:bg-water-50 transition-colors">
            <Icon size={18} className={color} />
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

export function PublicDashboardPage() {
  const [assistantOpen, setAssistantOpen] = useState(false);
  const overview = usePublicOverview();
  const datasets = usePublicDatasets({ page: 1, size: 50 });
  const alerts = usePublicAlerts({ page: 1, size: 50 });
  const map = usePublicMap();
  const waterExtents = usePublicWaterExtents({ page: 1, size: 200 });

  return (
    <div className="min-h-screen bg-canvas">
      {/* Public header — same product identity, no account chrome. */}
      <header className="border-b border-border bg-white sticky top-0 z-20">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <Link to="/public" className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-water-700 text-base font-semibold text-white shadow-sm shadow-water-700/20">
              LW
            </span>
            <div className="leading-tight">
              <p className="text-lg font-semibold text-ink tracking-tight">LakeWatch Public</p>
              <p className="text-xs text-muted uppercase tracking-wider">Lake Malawi monitoring · open data</p>
            </div>
          </Link>
          <Link
            to="/login"
            className="btn-secondary text-sm px-3 py-1.5"
          >
            Staff sign in
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6 lg:py-8">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-water-700">Public dashboard</p>
            <h1 className="mt-1 text-2xl font-bold text-ink tracking-tight">Lake Malawi at a glance</h1>
            <p className="mt-2 text-sm text-muted max-w-2xl">
              Published datasets, study areas and disaster alerts for Lake Malawi.
              Read-only — no account required. Data shown only where the team has
              explicitly published it.
            </p>
          </div>
          <button
            type="button"
            className="btn-secondary shrink-0"
            aria-expanded={assistantOpen}
            onClick={() => setAssistantOpen((open) => !open)}
          >
            {assistantOpen ? "Close AI panel" : "Ask AI"}
          </button>
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
          <div className="flex items-start gap-3 rounded-md border border-danger/30 bg-danger-light px-4 py-3 text-sm text-danger-dark">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <div>
              <p className="font-medium">{overview.data.alerts.by_severity.critical} active published alert(s) are at critical severity.</p>
              <p className="mt-1 text-xs text-danger/70">Review the response record on the staff console.</p>
            </div>
          </div>
        ) : null}

        {/* Map centrepiece */}
        <Card className="overflow-hidden">
          <CardHeader
            title="Lake Malawi — published observations"
            description="Satellite-derived water extents and study areas. Lake boundary shown for reference."
          />
          <div className="h-[34rem] lg:h-[42rem]">
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
          </div>
        </Card>

        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {/* Alerts */}
          <Card className="col-span-2 lg:col-span-1">
            <CardHeader
              title="Active public alerts"
              description="Open or acknowledged alerts published by the team."
            />
          {alerts.isLoading ? (
            <LoadingRows rows={5} />
          ) : alerts.isError ? (
            <ErrorState error={alerts.error} onRetry={() => alerts.refetch()} />
          ) : alerts.data && alerts.data.items.length > 0 ? (
            <ul className="divide-y divide-border">
              {alerts.data.items.map((alert) => (
                <li key={alert.id} className="px-5 py-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-ink">{alert.message}</p>
                      <p className="text-xs text-muted">
                        {alert.severity}{alert.study_area_name ? ` · ${alert.study_area_name}` : ""}
                      </p>
                    </div>
                    <Badge className={STATUS_STYLE[alert.status] ?? STATUS_STYLE.open}>
                      {titleCase(alert.status)}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-ink-soft">
                    First seen {formatDateTime(alert.first_seen_at)}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="No public alerts"
              description="Alerts appear here only after the team publishes them."
              action={<p className="text-xs text-muted">Published alerts will appear here automatically.</p>}
            />
          )}
        </Card>

        {/* Published datasets */}
        <Card className="col-span-2 lg:col-span-2">
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
                      <Tr key={dataset.id} className="hover:bg-canvas/50 transition-colors">
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
        </div>
        {assistantOpen ? (
          <DashboardAssistantPanel
            metrics={[
              { label: "Published datasets", value: String(overview.data?.dataset_count ?? 0) },
              { label: "Study areas", value: String(overview.data?.study_area_count ?? 0) },
              {
                label: "Active alerts",
                value: String(
                  (overview.data?.alerts.by_status.open ?? 0) +
                    (overview.data?.alerts.by_status.acknowledged ?? 0),
                ),
              },
              {
                label: "Data coverage",
                value: overview.data?.coverage_start
                  ? `${formatDate(overview.data.coverage_start)} → ${formatDate(overview.data.coverage_end)}`
                  : "—",
              },
            ]}
            onClose={() => setAssistantOpen(false)}
          />
        ) : null}
        <p className="pb-6 text-xs text-muted">{overview.data?.provenance}</p>
      </main>
    </div>
  );
}
