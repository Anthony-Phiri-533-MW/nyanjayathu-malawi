import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Eye, Globe, StickyNote, Undo2 } from "lucide-react";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field, TextArea } from "@/components/ui/Field";
import { ErrorState, EmptyState, LoadingRows } from "@/components/ui/States";
import { DetailList, PageHeader, ProvisionalNote } from "@/components/PageHeader";
import { formatDateTime, statusStyle, titleCase } from "@/lib/format";
import { useAuth } from "@/auth/AuthContext";
import { useAlert, useAlertAction, usePublish } from "@/lib/hooks";

const RESPONSE_ICON = {
  acknowledged: Eye,
  note: StickyNote,
  resolved: CheckCircle2,
  reopened: Undo2,
} as const;

export function AlertDetailPage() {
  const params = useParams();
  const alertId = params.alertId ? Number(params.alertId) : null;
  const alert = useAlert(alertId);

  const [note, setNote] = useState("");
  const [severities, setSeverity] = useState<string>("");
  const [kind, setKind] = useState<string>("");
  const [actionError, setActionError] = useState<string | null>(null);

  const ack = useAlertAction("acknowledge");
  const addNote = useAlertAction("notes");
  const resolve = useAlertAction("resolve");
  const reopen = useAlertAction("reopen");
  const { can: hasPermission } = useAuth();
  const canPublish = hasPermission("public.publish");
  const publish = usePublish("alerts", ["disaster", "alerts"]);

  if (alert.isLoading) {
    return <LoadingRows rows={6} />;
  }
  if (alert.isError) {
    return (
      <div className="space-y-4">
        <Link to="/disaster/alerts" className="text-sm text-water-700 hover:text-water-800">
          ← Back to alerts
        </Link>
        <ErrorState error={alert.error} onRetry={() => alert.refetch()} />
      </div>
    );
  }
  if (!alert.data) {
    return <EmptyState title="Alert not found" />;
  }

  const a = alert.data;
  const busy = ack.isPending || addNote.isPending || resolve.isPending || reopen.isPending;

  const runAction = (
    action: "acknowledge" | "resolve" | "reopen" | "note",
  ) => {
    setActionError(null);
    const payload = {
      note: note.trim(),
      severity: severities ? (severities as "info" | "warning" | "critical") : undefined,
      kind: kind ? (kind as "flood" | "drought" | "water_quality" | "general") : undefined,
    };
    const mutation =
      action === "acknowledge" ? ack : action === "resolve" ? resolve : action === "reopen" ? reopen : addNote;
    mutation.mutate(
      { id: a.id, payload },
      {
        onSuccess: () => setNote(""),
        onError: (error) =>
          setActionError(error instanceof Error ? error.message : "Action failed"),
      },
    );
  };

  return (
    <div className="space-y-6">
      <Link to="/disaster/alerts" className="inline-flex items-center gap-1.5 text-sm text-water-700 hover:text-water-800">
        <ArrowLeft size={15} />
        Back to alerts
      </Link>

      <PageHeader
        title={`${titleCase(a.kind)} alert · ${a.indicator_name || a.indicator_key}`}
        description={a.message}
        actions={
          <>
            <Badge className={statusStyle(a.status)}>{a.status}</Badge>
            <Badge className={statusStyle(a.severity === "critical" ? "failed" : a.severity === "warning" ? "pending" : "")}>
              {a.severity}
            </Badge>
            {canPublish ? (
              <Button
                variant="secondary"
                size="sm"
                loading={publish.isPending}
                onClick={() => publish.mutate({ id: a.id, is_public: !a.is_public })}
              >
                <Globe size={14} />
                {a.is_public ? "Remove from public" : "Publish publicly"}
              </Button>
            ) : null}
          </>
        }
      />

      {a.severity !== "info" ? (
        <div className="rounded-md border border-signal-200 bg-signal-50 px-3 py-2 text-xs text-signal-700">
          <span className="font-semibold">Respond promptly.</span>{" "}
          {a.severity === "critical"
            ? "Critical severity (≥25% beyond the threshold per provisional bands)."
            : "Warning severity — condition is beyond the approved threshold."}
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Alert record" />
          <CardBody>
            <DetailList
              columns={2}
              items={[
                { label: "Study area", value: a.study_area_name ?? "—" },
                { label: "Indicator", value: `${a.indicator_name || a.indicator_key} (${a.indicator_key})` },
                {
                  label: "Value compared",
                  value: `${a.metric_value} ${a.unit}`,
                },
                {
                  label: "Metric source",
                  value:
                    a.metric_source === "forecast"
                      ? "Recorded forecast value"
                      : "Computed indicator result (observed)",
                },
                { label: "Metric date", value: a.metric_date ?? "—" },
                { label: "Hazard type", value: titleCase(a.kind) },
                { label: "First seen", value: formatDateTime(a.first_seen_at) },
                { label: "Last evaluated", value: formatDateTime(a.last_evaluated_at) },
                { label: "Times triggered", value: `${a.times_seen}×` },
                {
                  label: "Acknowledged",
                  value: a.acknowledged_at
                    ? `${formatDateTime(a.acknowledged_at)} by ${a.acknowledged_by_email ?? "unknown"}`
                    : "Not yet acknowledged",
                },
                {
                  label: "Resolved",
                  value: a.resolved_at
                    ? `${formatDateTime(a.resolved_at)} by ${a.resolved_by_email ?? "unknown"}`
                    : "—",
                },
              ]}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Threshold that was breached"
            description="Snapshot taken when the alert fired; threshold edits never rewrite it."
          />
          <CardBody>
            {a.threshold_snapshot && a.threshold_id ? (
              <>
                <DetailList
                  columns={2}
                  items={[
                    { label: "Threshold ID", value: `#${a.threshold_id}` },
                    { label: "Operator", value: a.threshold_snapshot.operator },
                    { label: "Reference value (low)", value: a.threshold_snapshot.value_low ?? "—" },
                    { label: "Reference value (high)", value: a.threshold_snapshot.value_high ?? "—" },
                    { label: "Approval", value: a.threshold_snapshot.approval_status },
                    { label: "Version", value: `v${a.threshold_snapshot.version}` },
                  ]}
                />
                {a.threshold_snapshot.approval_status !== "approved" ? (
                  <div className="mt-3">
                    <ProvisionalNote>
                      This alert was raised against a <strong>provisional</strong> threshold — it
                      should be reviewed by an administrator before operational response.
                    </ProvisionalNote>
                  </div>
                ) : null}
              </>
            ) : (
              <EmptyState title="No threshold snapshot on this alert" />
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Respond" description="All actions are recorded below and in the audit log." />
        <CardBody>
          {actionError ? (
            <p className="mb-3 rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-sm text-danger-dark">
              {actionError}
            </p>
          ) : null}
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className="field-label">Severity (set on acknowledge/resolve)</span>
              <select className="input h-9 w-44" value={severities} onChange={(e) => setSeverity(e.target.value)}>
                <option value="">Keep current</option>
                <option value="critical">Critical</option>
                <option value="warning">Warning</option>
                <option value="info">Info</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="field-label">Hazard type (set on acknowledge)</span>
              <select className="input h-9 w-44" value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="">Keep current</option>
                <option value="flood">Flood</option>
                <option value="drought">Drought</option>
                <option value="water_quality">Water quality</option>
                <option value="general">General</option>
              </select>
            </label>
          </div>
          <Field label="Response note" htmlFor="response-note" hint="Optional for acknowledge/resolve; required practice for notes.">
            <TextArea
              id="response-note"
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="What was reviewed or decided, and by whom…"
              className="mt-0"
            />
          </Field>
          <div className="mt-4 flex flex-wrap gap-2">
            {a.status === "open" ? (
              <Button variant="primary" onClick={() => runAction("acknowledge")} disabled={busy} loading={ack.isPending}>
                <Eye size={15} className="mr-1.5" />
                Acknowledge
              </Button>
            ) : null}
            <Button variant="secondary" onClick={() => runAction("note")} disabled={busy || !note.trim()} loading={addNote.isPending}>
              <StickyNote size={15} className="mr-1.5" />
              Add note
            </Button>
            {a.status !== "resolved" ? (
              <Button variant="secondary" onClick={() => runAction("resolve")} disabled={busy} loading={resolve.isPending}>
                <CheckCircle2 size={15} className="mr-1.5" />
                Resolve
              </Button>
            ) : null}
            {a.status === "resolved" ? (
              <Button variant="secondary" onClick={() => runAction("reopen")} disabled={busy} loading={reopen.isPending}>
                <Undo2 size={15} className="mr-1.5" />
                Reopen
              </Button>
            ) : null}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Response history"
          description={`${a.responses.length} recorded response(s) — append-only.`}
        />
        <CardBody>
          {a.responses.length === 0 ? (
            <EmptyState
              title="No responses recorded yet"
              description="Acknowledge this alert or add the first note to start the record."
            />
          ) : (
            <ol className="space-y-4">
              {a.responses.map((r) => {
                const Icon = RESPONSE_ICON[r.response_type] ?? StickyNote;
                return (
                  <li key={r.id} className="flex gap-3">
                    <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border bg-canvas">
                      <Icon size={15} className="text-ink-soft" />
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm">
                        <span className="font-medium text-ink">{titleCase(r.response_type)}</span>
                        {r.actor_email ? <span className="text-muted"> · {r.actor_email}</span> : null}
                        <span className="text-muted"> · {formatDateTime(r.created_at)}</span>
                      </p>
                      {r.note ? <p className="mt-0.5 whitespace-pre-wrap text-sm text-ink-soft">{r.note}</p> : null}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
