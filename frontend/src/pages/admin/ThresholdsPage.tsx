import { useState } from "react";
import { History, Plus, Trash2 } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { PageHeader, ProvisionalNote } from "@/components/PageHeader";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Checkbox, Field, Select, TextArea, TextInput } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError } from "@/lib/api";
import {
  useCreateThreshold,
  useDeleteThreshold,
  useIndicatorDefinitions,
  useThresholds,
  useThresholdVersions,
  useUpdateThreshold,
} from "@/lib/hooks";
import { formatDateTime, statusStyle, titleCase } from "@/lib/format";
import type { ApprovalStatus, Threshold, ThresholdOperator } from "@/lib/types";

const OPERATORS: ThresholdOperator[] = ["gt", "gte", "lt", "lte", "between"];
const APPROVALS: ApprovalStatus[] = ["provisional", "pending_review", "approved"];

const OPERATOR_LABEL: Record<ThresholdOperator, string> = {
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  between: "between",
};

export function ThresholdsPage() {
  const { can } = useAuth();
  const [search, setSearch] = useState("");
  const [approval, setApproval] = useState("");
  const [page, setPage] = useState(1);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Threshold | null>(null);
  const [historyId, setHistoryId] = useState<number | null>(null);
  const [banner, setBanner] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const thresholds = useThresholds({
    search: search || undefined,
    approval_status: approval || undefined,
    page,
    size: 20,
  });
  const definitions = useIndicatorDefinitions();
  const remove = useDeleteThreshold();

  const canWrite = can("admin.thresholds.write");
  const provisionalCount = (thresholds.data?.items ?? []).filter((t) => t.is_provisional).length;

  return (
    <div>
      <PageHeader
        title="Indicator thresholds"
        description="Thresholds define when an indicator value is flagged for attention (LOW_QUALITY / threshold breach). Values are configuration, not results: any setting that has not been reviewed is marked provisional and must not be treated as an operational standard."
        actions={
          canWrite ? (
            <Button onClick={() => setShowForm((v) => !v)}>
              <Plus size={16} /> New threshold
            </Button>
          ) : null
        }
      />

      {provisionalCount > 0 ? (
        <div className="mb-4">
          <ProvisionalNote>
            {provisionalCount} threshold(s) on this page are provisional and have not been
            scientifically validated for Lake Malawi. Review before using them to flag results.
          </ProvisionalNote>
        </div>
      ) : null}

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

      {showForm && canWrite ? (
        <ThresholdForm
          definitions={(definitions.data ?? []).map((d) => ({
            key: d.key,
            name: d.name,
            unit: d.unit,
            isProxy: d.is_proxy,
          }))}
          onClose={() => setShowForm(false)}
          onDone={(message) => {
            setShowForm(false);
            setBanner({ tone: "ok", text: message });
          }}
          onError={(text) => setBanner({ tone: "error", text })}
        />
      ) : null}

      {editing ? (
        <ThresholdForm
          definitions={(definitions.data ?? []).map((d) => ({
            key: d.key,
            name: d.name,
            unit: d.unit,
            isProxy: d.is_proxy,
          }))}
          existing={editing}
          onClose={() => setEditing(null)}
          onDone={(message) => {
            setEditing(null);
            setBanner({ tone: "ok", text: message });
          }}
          onError={(text) => setBanner({ tone: "error", text })}
        />
      ) : null}

      {historyId !== null ? (
        <VersionHistory thresholdId={historyId} onClose={() => setHistoryId(null)} />
      ) : null}

      <Card>
        <CardHeader
          title="Configured thresholds"
          description={`${thresholds.data?.total ?? 0} threshold(s)`}
          actions={
            <div className="flex gap-2">
              <Select
                className="w-44"
                value={approval}
                onChange={(e) => {
                  setApproval(e.target.value);
                  setPage(1);
                }}
              >
                <option value="">All approval states</option>
                {APPROVALS.map((a) => (
                  <option key={a} value={a}>
                    {titleCase(a)}
                  </option>
                ))}
              </Select>
              <TextInput
                className="w-56"
                placeholder="Search indicator"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
            </div>
          }
        />

        {thresholds.isLoading ? (
          <LoadingRows />
        ) : thresholds.isError ? (
          <ErrorState error={thresholds.error} onRetry={() => thresholds.refetch()} />
        ) : thresholds.data && thresholds.data.items.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Indicator</Th>
                  <Th>Rule</Th>
                  <Th>Approval</Th>
                  <Th>Version</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {thresholds.data.items.map((t) => (
                  <Tr key={t.id}>
                    <Td>
                      <p className="font-medium text-ink">{t.indicator_name}</p>
                      <p className="text-xs text-muted">{t.indicator_key}</p>
                    </Td>
                    <Td>
                      <p className="tabular">
                        {OPERATOR_LABEL[t.operator]}{" "}
                        {t.operator === "between"
                          ? `${t.value_low} – ${t.value_high}`
                          : (t.value_low ?? t.value_high)}{" "}
                        {t.unit}
                      </p>
                      {t.justification ? (
                        <p className="mt-0.5 max-w-md text-xs text-muted">{t.justification}</p>
                      ) : (
                        <p className="mt-0.5 text-xs text-warning-dark">
                          No justification recorded — provisional.
                        </p>
                      )}
                    </Td>
                    <Td>
                      <Badge className={statusStyle(t.approval_status)}>
                        {titleCase(t.approval_status)}
                      </Badge>
                      {t.is_provisional ? (
                        <p className="mt-1 text-xs text-signal-700">Provisional</p>
                      ) : null}
                    </Td>
                    <Td>
                      <p className="tabular">v{t.version}</p>
                      <p className="text-xs text-muted">{formatDateTime(t.updated_at ?? t.created_at)}</p>
                    </Td>
                    <Td align="right">
                      <div className="flex flex-wrap justify-end gap-1">
                        <Button variant="secondary" size="sm" onClick={() => setHistoryId(t.id)}>
                          <History size={14} />
                        </Button>
                        {canWrite ? (
                          <>
                            <Button variant="secondary" size="sm" onClick={() => setEditing(t)}>
                              Edit
                            </Button>
                            <Button
                              variant="secondary"
                              size="sm"
                              loading={remove.isPending}
                              onClick={async () => {
                                if (!window.confirm(`Delete the ${t.indicator_name} threshold?`)) return;
                                try {
                                  await remove.mutateAsync(t.id);
                                  setBanner({ tone: "ok", text: `Deleted ${t.indicator_name} threshold.` });
                                } catch (error) {
                                  setBanner({
                                    tone: "error",
                                    text: error instanceof ApiError ? error.message : "Delete failed.",
                                  });
                                }
                              }}
                            >
                              <Trash2 size={14} />
                            </Button>
                          </>
                        ) : null}
                      </div>
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              page={thresholds.data.page}
              pages={thresholds.data.pages}
              total={thresholds.data.total}
              onChange={setPage}
            />
          </>
        ) : (
          <EmptyState
            title="No thresholds configured"
            description="Thresholds are optional; indicators compute without them. Add one only when you have a defensible value for Lake Malawi."
          />
        )}
      </Card>
    </div>
  );
}

function ThresholdForm({
  definitions,
  existing,
  onClose,
  onDone,
  onError,
}: {
  definitions: Array<{ key: string; name: string; unit: string; isProxy: boolean }>;
  existing?: Threshold;
  onClose: () => void;
  onDone: (message: string) => void;
  onError: (text: string) => void;
}) {
  const create = useCreateThreshold();
  const update = useUpdateThreshold();

  const [indicatorKey, setIndicatorKey] = useState(existing?.indicator_key ?? definitions[0]?.key ?? "");
  const definition = definitions.find((d) => d.key === indicatorKey);

  const [operator, setOperator] = useState<ThresholdOperator>(existing?.operator ?? "gt");
  const [valueLow, setValueLow] = useState(existing?.value_low != null ? String(existing.value_low) : "");
  const [valueHigh, setValueHigh] = useState(existing?.value_high != null ? String(existing.value_high) : "");
  const [justification, setJustification] = useState(existing?.justification ?? "");
  const [reference, setReference] = useState(existing?.reference ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [approvalStatus, setApprovalStatus] = useState<ApprovalStatus>(
    existing?.approval_status ?? "provisional",
  );
  const [isEnabled, setIsEnabled] = useState(existing?.is_enabled ?? true);
  const [changeNote, setChangeNote] = useState("");

  const pending = create.isPending || update.isPending;
  const unit = definition?.unit ?? existing?.unit ?? "";
  const isBetween = operator === "between";

  const submit = async () => {
    const low = valueLow === "" ? null : Number(valueLow);
    const high = valueHigh === "" ? null : Number(valueHigh);
    if (isBetween && (low === null || high === null)) {
      onError("A 'between' rule needs both a lower and an upper value.");
      return;
    }
    if (!isBetween && low === null && high === null) {
      onError("Provide the threshold value.");
      return;
    }
    const selected = definition ?? {
      key: existing?.indicator_key ?? indicatorKey,
      name: existing?.indicator_name ?? indicatorKey,
      unit,
      isProxy: false,
    };

    const payload = {
      indicator_key: selected.key,
      indicator_name: selected.name,
      unit,
      operator,
      value_low: isBetween ? low : low,
      value_high: isBetween ? high : null,
      description: description.trim(),
      justification: justification.trim(),
      reference: reference.trim(),
      approval_status: approvalStatus,
      is_enabled: isEnabled,
    };

    try {
      if (existing) {
        await update.mutateAsync({
          id: existing.id,
          payload: { ...payload, change_note: changeNote.trim() || "Updated via console" },
        });
        onDone(`Updated the ${selected.name} threshold.`);
      } else {
        const created = await create.mutateAsync(payload);
        onDone(`Created the ${created.indicator_name} threshold.`);
      }
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "Could not save the threshold.");
    }
  };

  return (
    <Card className="mb-5">
      <CardHeader
        title={existing ? `Edit — ${existing.indicator_name}` : "New threshold"}
        description="Record the justification and a citation. An unreviewed rule stays provisional."
        actions={
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
        }
      />
      <form
        className="grid gap-4 px-5 py-4 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Field label="Indicator" htmlFor="th-indicator" required>
          <Select
            id="th-indicator"
            value={indicatorKey}
            onChange={(e) => setIndicatorKey(e.target.value)}
            disabled={Boolean(existing)}
          >
            {definitions.map((d) => (
              <option key={d.key} value={d.key}>
                {d.name}
                {d.isProxy ? " (proxy)" : ""}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Operator" htmlFor="th-operator" required>
          <Select
            id="th-operator"
            value={operator}
            onChange={(e) => setOperator(e.target.value as ThresholdOperator)}
          >
            {OPERATORS.map((op) => (
              <option key={op} value={op}>
                {OPERATOR_LABEL[op]} ({op})
              </option>
            ))}
          </Select>
        </Field>
        <Field
          label={isBetween ? "Lower bound" : "Value"}
          htmlFor="th-low"
          hint={unit ? `Unit: ${unit}` : undefined}
          required
        >
          <TextInput
            id="th-low"
            type="number"
            step="any"
            value={valueLow}
            onChange={(e) => setValueLow(e.target.value)}
          />
        </Field>
        {isBetween ? (
          <Field label="Upper bound" htmlFor="th-high" required>
            <TextInput
              id="th-high"
              type="number"
              step="any"
              value={valueHigh}
              onChange={(e) => setValueHigh(e.target.value)}
            />
          </Field>
        ) : null}
        <Field
          label="Justification"
          htmlFor="th-justification"
          className="sm:col-span-2"
          hint="Why this value is defensible. Required before approval."
        >
          <TextArea
            id="th-justification"
            rows={2}
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
          />
        </Field>
        <Field label="Reference" htmlFor="th-reference" hint="Citation or source for the value.">
          <TextInput id="th-reference" value={reference} onChange={(e) => setReference(e.target.value)} />
        </Field>
        <Field label="Approval status" htmlFor="th-approval">
          <Select
            id="th-approval"
            value={approvalStatus}
            onChange={(e) => setApprovalStatus(e.target.value as ApprovalStatus)}
          >
            {APPROVALS.map((a) => (
              <option key={a} value={a}>
                {titleCase(a)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Description" htmlFor="th-desc" className="sm:col-span-2">
          <TextArea
            id="th-desc"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        {existing ? (
          <Field label="Change note" htmlFor="th-note" className="sm:col-span-2" hint="Recorded in the version history.">
            <TextInput
              id="th-note"
              value={changeNote}
              onChange={(e) => setChangeNote(e.target.value)}
              placeholder="e.g. Tightened after 2024 field campaign"
            />
          </Field>
        ) : null}
        <div className="sm:col-span-2">
          <Checkbox
            label="Enabled"
            checked={isEnabled}
            onChange={(e) => setIsEnabled(e.currentTarget.checked)}
          />
        </div>
        <div className="sm:col-span-2">
          <Button type="submit" loading={pending}>
            {existing ? "Save changes" : "Create threshold"}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function VersionHistory({
  thresholdId,
  onClose,
}: {
  thresholdId: number;
  onClose: () => void;
}) {
  const versions = useThresholdVersions(thresholdId);

  return (
    <Card className="mb-5">
      <CardHeader
        title="Version history"
        description="Every change is retained with its snapshot. Historical versions are never edited."
        actions={
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close
          </Button>
        }
      />
      {versions.isLoading ? (
        <LoadingRows rows={3} />
      ) : versions.isError ? (
        <ErrorState error={versions.error} onRetry={() => versions.refetch()} />
      ) : (
        <CardBody>
          <ol className="space-y-3">
            {(versions.data ?? []).map((v) => (
              <li key={v.id} className="border-l-2 border-water-200 pl-3">
                <p className="text-sm font-medium text-ink">
                  v{v.version} <span className="text-muted">· {formatDateTime(v.created_at)}</span>
                </p>
                <p className="text-xs text-muted">
                  {v.changed_by_email ?? "—"} — {v.change_note || "No note"}
                </p>
              </li>
            ))}
          </ol>
        </CardBody>
      )}
    </Card>
  );
}
