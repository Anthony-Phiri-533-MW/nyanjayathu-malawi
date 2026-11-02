import { useState } from "react";
import { RefreshCw, XCircle } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError } from "@/lib/api";
import { useCancelJob, useJobs, useRetryJob } from "@/lib/hooks";
import { formatDateTime, statusStyle } from "@/lib/format";
import type { Job } from "@/lib/types";

const JOB_KINDS = ["ingestion", "processing", "indicator", "export"];

export function JobsPage() {
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(1);
  const [banner, setBanner] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const jobs = useJobs({
    status: status || undefined,
    kind: kind || undefined,
    page,
    size: 25,
  });
  const cancel = useCancelJob();
  const retry = useRetryJob();

  const resetPage = () => setPage(1);

  return (
    <div>
      <PageHeader
        title="Jobs"
        description="Background work queued on this deployment: ingestion, preprocessing, indicator computation and exports. Failed jobs record their error; retrying requeues the same parameters."
      />

      {banner ? (
        <div
          className={
            banner.tone === "ok"
              ? "mb-4 rounded-md border border-success/30 bg-success-light px-3 py-2 text-sm text-success-dark"
              : "mb-4 rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-sm text-danger-dark"
          }
        >
          {banner.text}
        </div>
      ) : null}

      <Card>
        <CardHeader
          title="Queue"
          description={`${jobs.data?.total ?? 0} job(s)`}
          actions={
            <div className="flex gap-2">
              <Select
                className="w-40"
                value={kind}
                onChange={(e) => {
                  setKind(e.target.value);
                  resetPage();
                }}
              >
                <option value="">All kinds</option>
                {JOB_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </Select>
              <Select
                className="w-40"
                value={status}
                onChange={(e) => {
                  setStatus(e.target.value);
                  resetPage();
                }}
              >
                <option value="">All statuses</option>
                <option value="pending">Pending</option>
                <option value="running">Running</option>
                <option value="succeeded">Succeeded</option>
                <option value="failed">Failed</option>
                <option value="canceled">Canceled</option>
              </Select>
              <Button variant="secondary" size="sm" onClick={() => jobs.refetch()}>
                <RefreshCw size={14} /> Refresh
              </Button>
            </div>
          }
        />

        {jobs.isLoading ? (
          <LoadingRows rows={6} />
        ) : jobs.isError ? (
          <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />
        ) : jobs.data && jobs.data.items.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Job</Th>
                  <Th>Status</Th>
                  <Th>Progress</Th>
                  <Th>Created</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {jobs.data.items.map((job) => (
                  <JobRow
                    key={job.id}
                    job={job}
                    onCancel={async () => {
                      try {
                        await cancel.mutateAsync(job.id);
                        setBanner({ tone: "ok", text: `Canceled job #${job.id}.` });
                      } catch (error) {
                        setBanner({
                          tone: "error",
                          text: error instanceof ApiError ? error.message : "Cancel failed.",
                        });
                      }
                    }}
                    onRetry={async () => {
                      try {
                        await retry.mutateAsync(job.id);
                        setBanner({ tone: "ok", text: `Requeued job #${job.id}.` });
                      } catch (error) {
                        setBanner({
                          tone: "error",
                          text: error instanceof ApiError ? error.message : "Retry failed.",
                        });
                      }
                    }}
                    busy={cancel.isPending || retry.isPending}
                  />
                ))}
              </tbody>
            </Table>
            <Pagination
              page={jobs.data.page}
              pages={jobs.data.pages}
              total={jobs.data.total}
              onChange={setPage}
            />
          </>
        ) : (
          <EmptyState title="No jobs" description="Queued work will appear here." />
        )}
      </Card>
    </div>
  );
}

function JobRow({
  job,
  onCancel,
  onRetry,
  busy,
}: {
  job: Job;
  onCancel: () => void;
  onRetry: () => void;
  busy: boolean;
}) {
  const active = job.status === "pending" || job.status === "running";
  const failed = job.status === "failed";

  return (
    <Tr>
      <Td>
        <p className="font-medium text-ink">
          #{job.id} · {job.kind}
        </p>
        <p className="max-w-md text-xs text-muted">{job.message || job.error || "—"}</p>
        {job.attempts > 0 ? (
          <p className="text-xs text-muted">Attempt {job.attempts}</p>
        ) : null}
      </Td>
      <Td>
        <Badge className={statusStyle(job.status)}>{job.status}</Badge>
      </Td>
      <Td>
        <div className="h-1.5 w-24 overflow-hidden rounded-full bg-canvas">
          <div
            className="h-full rounded-full bg-water-600"
            style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }}
          />
        </div>
      </Td>
      <Td className="whitespace-nowrap text-xs">{formatDateTime(job.created_at)}</Td>
      <Td align="right">
        {active ? (
          <Button variant="secondary" size="sm" loading={busy} onClick={onCancel}>
            <XCircle size={14} /> Cancel
          </Button>
        ) : failed ? (
          <Button variant="secondary" size="sm" loading={busy} onClick={onRetry}>
            <RefreshCw size={14} /> Retry
          </Button>
        ) : (
          <span className="text-xs text-muted">—</span>
        )}
      </Td>
    </Tr>
  );
}
