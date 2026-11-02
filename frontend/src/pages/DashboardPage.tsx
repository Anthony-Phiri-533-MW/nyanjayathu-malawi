import { Link } from "react-router-dom";
import {
  Boxes,
  Database,
  FileDown,
  ListChecks,
  SlidersHorizontal,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ErrorState, LoadingRows } from "@/components/ui/States";
import { useDataSources, useDatasets, useExports, useJobs, useThresholds, useUsers } from "@/lib/hooks";
import { formatDateTime, statusStyle } from "@/lib/format";

/** Small count tile used on the dashboard. */
function StatTile({
  label,
  value,
  hint,
  to,
  icon: Icon,
}: {
  label: string;
  value: React.ReactNode;
  hint: string;
  to: string;
  icon: LucideIcon;
}) {
  return (
    <Link to={to} className="card block px-5 py-4 transition-shadow hover:shadow-pop">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
          <p className="mt-1 text-2xl font-semibold text-ink tabular">{value}</p>
          <p className="mt-1 text-xs text-muted">{hint}</p>
        </div>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-water-50 text-water-700">
          <Icon size={18} />
        </span>
      </div>
    </Link>
  );
}

export function DashboardPage() {
  const { user, can } = useAuth();

  const datasets = useDatasets({ page: 1, size: 1 });
  const sources = useDataSources({ page: 1, size: 1 });
  const thresholds = useThresholds({ page: 1, size: 1 });
  const users = useUsers({ page: 1, size: 1 });
  const jobs = useJobs({ page: 1, size: 8 });
  const exports = useExports({ page: 1, size: 1 });

  return (
    <div>
      <PageHeader
        title={`Welcome, ${user?.full_name.split(" ")[0] ?? "researcher"}`}
        description="Satellite-derived water level and water-quality monitoring for Lake Malawi. Observed retrievals and derived indicators are shown separately throughout."
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {can("research.datasets.read") ? (
          <StatTile
            label="Datasets"
            value={datasets.data?.total ?? "—"}
            hint="Stored retrieved and derived data"
            to="/research/datasets"
            icon={Boxes}
          />
        ) : null}
        {can("admin.data_sources.read") ? (
          <StatTile
            label="Data sources"
            value={sources.data?.total ?? "—"}
            hint="Configured provider integrations"
            to="/admin/data-sources"
            icon={Database}
          />
        ) : null}
        {can("admin.thresholds.read") ? (
          <StatTile
            label="Thresholds"
            value={thresholds.data?.total ?? "—"}
            hint="Flagging rules (review provisional entries)"
            to="/admin/thresholds"
            icon={SlidersHorizontal}
          />
        ) : null}
        {can("admin.users.read") ? (
          <StatTile
            label="User accounts"
            value={users.data?.total ?? "—"}
            hint="Administrators and researchers"
            to="/admin/users"
            icon={Users}
          />
        ) : null}
        {can("research.exports.download") ? (
          <StatTile
            label="Exports"
            value={exports.data?.total ?? "—"}
            hint="Generated research outputs"
            to="/research/exports"
            icon={FileDown}
          />
        ) : null}
      </div>

      <Card className="mt-6">
        <CardHeader
          title="Recent jobs"
          description="Ingestion, preprocessing, indicator and export work queued on this deployment."
          actions={
            <Link to="/research/jobs" className="btn-ghost px-2.5 py-1.5 text-sm">
              View all
            </Link>
          }
        />
        {jobs.isLoading ? (
          <LoadingRows rows={4} />
        ) : jobs.isError ? (
          <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />
        ) : jobs.data && jobs.data.items.length > 0 ? (
          <ul className="divide-y divide-border">
            {jobs.data.items.map((job) => (
              <li key={job.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink-soft">
                    {job.kind} job #{job.id}
                  </p>
                  <p className="truncate text-xs text-muted">
                    {job.message || (job.error ?? "Queued")}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted">{formatDateTime(job.created_at)}</span>
                  <Badge className={statusStyle(job.status)}>{job.status}</Badge>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <CardBody>
            <p className="flex items-center gap-2 text-sm text-muted">
              <ListChecks size={16} /> No jobs have been queued yet.
            </p>
          </CardBody>
        )}
      </Card>
    </div>
  );
}
