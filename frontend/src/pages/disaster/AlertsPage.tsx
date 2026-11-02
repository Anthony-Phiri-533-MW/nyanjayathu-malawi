import { useState } from "react";
import { Link } from "react-router-dom";
import { Play, ShieldAlert } from "lucide-react";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ErrorState, EmptyState, LoadingRows } from "@/components/ui/States";
import { PageHeader, ProvisionalNote } from "@/components/PageHeader";
import { useAlerts, useRunEvaluation } from "@/lib/hooks";
import { formatDateTime, formatNumber } from "@/lib/format";
import type { AlertSeverity, AlertStatus } from "@/lib/types";

/**
 * Semantic colours: severity drives the badge, never decoration.
 * 30-60-10 rule — the amber `signal` class is the warning state, danger red is
 * reserved for critical.
 */
const SEVERITY_STYLE: Record<AlertSeverity, string> = {
  critical: "bg-danger-light text-danger-dark border border-danger/30",
  warning: "bg-signal-100 text-signal-700 border border-signal-200",
  info: "bg-canvas text-muted border border-border",
};

const STATUS_STYLE: Record<AlertStatus, string> = {
  open: "bg-water-50 text-water-800 border border-water-200",
  acknowledged: "bg-info-light text-info-dark border border-info/30",
  resolved: "bg-success-light text-success-dark border border-success/30",
};

export function AlertsPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [includeProvisional, setIncludeProvisional] = useState(false);
  const alerts = useAlerts({
    status: statusFilter || undefined,
    severity: severityFilter || undefined,
    kind: kindFilter || undefined,
    size: 100,
  });
  const evaluation = useRunEvaluation();
  const [evalSummary, setEvalSummary] = useState<string | null>(null);
  const [evalError, setEvalError] = useState<string | null>(null);

  const runEvaluation = () => {
    setEvalError(null);
    setEvalSummary(null);
    evaluation.mutate(
      { include_provisional: includeProvisional },
      {
        onSuccess: (result) => {
          setEvalSummary(
            `Evaluation finished: ${result.thresholds_used} threshold(s) checked on ` +
              `${result.pairs_considered} pair(s); ${result.breached} breach(es), ` +
              `${result.alerts_created} new alert(s), ${result.alerts_updated} updated, ` +
              `${result.pairs_skipped} skipped (no data).`,
          );
        },
        onError: (error) => {
          setEvalError(error instanceof Error ? error.message : "Evaluation failed");
        },
      },
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Disaster alerts"
        description="Threshold evaluations raise alerts here; each response (acknowledge, note, resolve) is recorded permanently."
      />

      {evalError ? (
        <div className="rounded-md border border-danger/30 bg-danger-light px-4 py-3 text-sm text-danger-dark">
          Evaluation failed: {evalError}
        </div>
      ) : null}
      {evalSummary ? (
        <div className="rounded-md border border-water-200 bg-surface px-4 py-3 text-sm text-ink-soft">
          {evalSummary}
        </div>
      ) : null}

      <div className="card flex flex-wrap items-end gap-4 px-4 py-4">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium uppercase tracking-wide text-muted">Status</span>
          <select
            className="input h-9 w-40"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium uppercase tracking-wide text-muted">Severity</span>
          <select
            className="input h-9 w-40"
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
          >
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium uppercase tracking-wide text-muted">Hazard type</span>
          <select
            className="input h-9 w-40"
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
          >
            <option value="">All types</option>
            <option value="flood">Flood</option>
            <option value="drought">Drought</option>
            <option value="water_quality">Water quality</option>
            <option value="general">General</option>
          </select>
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm text-ink-soft">
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-border text-water-700 focus:ring-water-600"
            checked={includeProvisional}
            onChange={(e) => setIncludeProvisional(e.target.checked)}
          />
          Include provisional thresholds
        </label>
        <div className="ml-auto pb-1">
          <Button
            variant="secondary"
            onClick={runEvaluation}
            disabled={evaluation.isPending || includeProvisional === undefined}
            loading={evaluation.isPending}
          >
            <Play size={16} className="mr-1.5" />
            Run evaluation
          </Button>
        </div>
      </div>

      <ProvisionalNote>
        Severity bands and hazard-type mapping are provisional defaults documented in the
        README; alerts always record the exact threshold and metric value that triggered them.
      </ProvisionalNote>

      <Card>
        <CardHeader
          title="Alerts"
          description={
            alerts.data
              ? `${alerts.data.items.length} shown of ${alerts.data.total} — ordered by severity, then most recent.`
              : undefined
          }
        />
        <CardBody>
          {alerts.isLoading ? (
            <LoadingRows rows={5} />
          ) : alerts.isError ? (
            <ErrorState error={alerts.error} />
          ) : !alerts.data || alerts.data.items.length === 0 ? (
            <EmptyState
              title="No alerts match"
              description="Run an evaluation against the approved thresholds to check current conditions."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Indicator</th>
                    <th>Study area</th>
                    <th>Type</th>
                    <th>Value</th>
                    <th>Status</th>
                    <th>Last evaluated</th>
                    <th className="w-24"></th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.data.items.map((alert) => (
                    <tr key={alert.id} className="align-top">
                      <td>
                        <Badge className={SEVERITY_STYLE[alert.severity]}>{alert.severity}</Badge>
                      </td>
                      <td>
                        <p className="font-medium text-ink">
                          {alert.indicator_name || alert.indicator_key}
                        </p>
                        <p className="text-xs text-muted">
                          {alert.metric_source === "forecast" ? "forecast value" : "observed value"}
                          {alert.times_seen > 1 ? ` · seen ${alert.times_seen}×` : ""}
                        </p>
                      </td>
                      <td className="text-ink-soft">{alert.study_area_name ?? "—"}</td>
                      <td className="capitalize text-ink-soft">{alert.kind}</td>
                      <td className="text-ink-soft">
                        {formatNumber(alert.metric_value, { unit: alert.unit })}
                        {alert.metric_date ? (
                          <p className="text-xs text-muted">{alert.metric_date}</p>
                        ) : null}
                      </td>
                      <td>
                        <Badge className={STATUS_STYLE[alert.status]}>{alert.status}</Badge>
                      </td>
                      <td className="text-xs text-muted">
                        {formatDateTime(alert.last_evaluated_at)}
                      </td>
                      <td>
                        <Link
                          to={`/disaster/alerts/${alert.id}`}
                          className="text-sm font-medium text-water-700 hover:text-water-800"
                        >
                          Review →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader title="How evaluation works" />
          <CardBody>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-soft">
              <li>Approved thresholds (Admin → Thresholds) are always evaluated; provisional ones only when you opt in above.</li>
              <li>For each study area and indicator: the latest recorded forecast value is used if present, otherwise the latest computed indicator value.</li>
              <li>No data for a pair? It is skipped and reported — the engine never invents values.</li>
              <li>An already-open alert is updated (value, count) instead of duplicated.</li>
            </ul>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Response workflow" />
          <CardBody>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-soft">
              <li>Open → acknowledged → resolved; reopening records the renewed breach.</li>
              <li>Every acknowledge, note and resolve is stored on the alert and audit-logged.</li>
              <li>Open the review screen for the complete response history.</li>
            </ul>
            <div className="mt-3 flex items-center gap-2 text-xs text-muted">
              <ShieldAlert size={14} />
              Responding requires the <span className="font-medium">disaster.alerts.respond</span> permission.
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
