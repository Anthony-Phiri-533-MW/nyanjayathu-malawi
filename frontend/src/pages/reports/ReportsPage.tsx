import { useState } from "react";
import { Ban, Download, FileText, RotateCcw } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextArea, TextInput } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError, downloadFile } from "@/lib/api";
import {
  useCancelReport,
  useCreateReport,
  useReports,
  useRetryReport,
  useStudyAreas,
} from "@/lib/hooks";
import { formatBytes, formatDateTime, statusStyle, titleCase } from "@/lib/format";
import type { Report, ReportFormat, ReportInput, ReportPeriodType, ReportSection } from "@/lib/types";

/**
 * Mirrors `REPORT_SECTIONS` on the backend. Report files freeze these sections
 * at build time; the PDF/CSV the job writes never changes afterwards.
 */
const SECTIONS: { key: ReportSection; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "indicators", label: "Indicator statistics" },
  { key: "forecasts", label: "Forecast values" },
  { key: "alerts", label: "Disaster alerts" },
];

const PERIOD_TYPES: { key: ReportPeriodType; label: string }[] = [
  { key: "daily", label: "Daily — today" },
  { key: "weekly", label: "Weekly — last 7 days" },
  { key: "monthly", label: "Monthly — this month so far" },
  { key: "quarterly", label: "Quarterly — this quarter so far" },
  { key: "annual", label: "Annual — this year so far" },
];

export function ReportsPage() {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const [banner, setBanner] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);

  const reports = useReports({ page, size: 20 });
  const cancel = useCancelReport();
  const retry = useRetryReport();
  const canCreate = can("reports.create");
  const canDownload = can("reports.download");

  // Downloads must go through fetch with the Authorization header — a plain
  // anchor link would 401 because the JWT lives in localStorage, not cookies.
  const handleDownload = async (report: Report) => {
    setDownloadingId(report.id);
    try {
      await downloadFile(`/reports/${report.id}/download`, report.file_name ?? undefined);
    } catch (error) {
      setBanner({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Report download failed.",
      });
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Reports"
        description="Periodic and custom reports drawn from indicator results, recorded forecasts and disaster alerts. Every report is a frozen snapshot: figures are computed once at build time and the stored file never changes."
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

      {canCreate ? (
        <ReportForm
          onDone={(message) => setBanner({ tone: "ok", text: message })}
          onError={(text) => setBanner({ tone: "error", text })}
        />
      ) : (
        <Card className="mb-5">
          <CardBody>
            <p className="text-sm text-muted">
              You can view reports but lack permission to build new ones.
            </p>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Report history"
          description={`${reports.data?.total ?? 0} report(s). Files become downloadable once the build succeeds.`}
          actions={
            <Button variant="secondary" size="sm" onClick={() => reports.refetch()}>
              Refresh
            </Button>
          }
        />
        {reports.isLoading ? (
          <LoadingRows rows={5} />
        ) : reports.isError ? (
          <ErrorState error={reports.error} onRetry={() => reports.refetch()} />
        ) : reports.data && reports.data.items.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Report</Th>
                  <Th>Period</Th>
                  <Th>Status</Th>
                  <Th>Size</Th>
                  <Th>Created</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {reports.data.items.map((report) => {
                  const ready =
                    report.status === "completed" &&
                    Boolean(report.file_name) &&
                    canDownload;
                  return (
                    <Tr key={report.id}>
                      <Td>
                        <p className="font-medium text-ink">
                          #{report.id} · {report.title}
                        </p>
                        <p className="text-xs text-muted">
                          {titleCase(report.kind)}
                          {report.period_type ? ` · ${report.period_type}` : ""} ·{" "}
                          {report.format.toUpperCase()}
                          {report.study_area_name ? ` · ${report.study_area_name}` : " · all study areas"}
                        </p>
                      </Td>
                      <Td className="whitespace-nowrap text-xs">
                        {report.period_start} → {report.period_end}
                      </Td>
                      <Td>
                        <Badge className={statusStyle(report.status)}>{report.status}</Badge>
                        {report.error ? (
                          <p className="mt-1 max-w-xs text-xs text-danger">{report.error}</p>
                        ) : null}
                      </Td>
                      <Td align="right">{formatBytes(report.size_bytes)}</Td>
                      <Td className="whitespace-nowrap text-xs">
                        {formatDateTime(report.created_at)}
                      </Td>
                      <Td align="right">
                        <div className="flex items-center justify-end gap-2">
                          {ready ? (
                            <Button
                              variant="secondary"
                              size="sm"
                              loading={downloadingId === report.id}
                              onClick={() => void handleDownload(report)}
                            >
                              <Download size={13} /> Download
                            </Button>
                          ) : (
                            <span className="text-xs text-muted">
                              {report.status === "completed"
                                ? "Ready"
                                : report.status === "queued"
                                  ? "Queued"
                                  : report.status === "building"
                                    ? "Building"
                                    : "Unavailable"}
                            </span>
                          )}
                          {canCreate && report.status === "queued" && report.job_status === "pending" ? (
                            <Button
                              variant="danger"
                              size="sm"
                              loading={cancel.isPending}
                              aria-label={`Cancel report ${report.id}`}
                              onClick={async () => {
                                try {
                                  await cancel.mutateAsync(report.id);
                                  setBanner({ tone: "ok", text: `Canceled report #${report.id}.` });
                                } catch (error) {
                                  setBanner({
                                    tone: "error",
                                    text: error instanceof ApiError ? error.message : "Cancel failed.",
                                  });
                                }
                              }}
                            >
                              <Ban size={13} /> Cancel
                            </Button>
                          ) : null}
                          {canCreate && (report.status === "failed" || report.status === "canceled") ? (
                            <Button
                              variant="secondary"
                              size="sm"
                              loading={retry.isPending}
                              aria-label={`Retry report ${report.id}`}
                              onClick={async () => {
                                try {
                                  await retry.mutateAsync(report.id);
                                  setBanner({ tone: "ok", text: `Requeued report #${report.id}.` });
                                } catch (error) {
                                  setBanner({
                                    tone: "error",
                                    text: error instanceof ApiError ? error.message : "Retry failed.",
                                  });
                                }
                              }}
                            >
                              <RotateCcw size={13} /> Retry
                            </Button>
                          ) : null}
                        </div>
                      </Td>
                    </Tr>
                  );
                })}
              </tbody>
            </Table>
            <Pagination
              page={reports.data.page}
              pages={reports.data.pages}
              total={reports.data.total}
              onChange={setPage}
            />
          </>
        ) : (
          <EmptyState
            title="No reports yet"
            description="Build a periodic or custom report above to produce a downloadable PDF or CSV file."
          />
        )}
      </Card>
    </div>
  );
}

function ReportForm({
  onDone,
  onError,
}: {
  onDone: (message: string) => void;
  onError: (text: string) => void;
}) {
  const create = useCreateReport();
  const studyAreas = useStudyAreas();

  const [kind, setKind] = useState<"periodic" | "custom">("periodic");
  const [periodType, setPeriodType] = useState<ReportPeriodType>("monthly");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [format, setFormat] = useState<ReportFormat>("pdf");
  const [studyAreaId, setStudyAreaId] = useState("");
  const [sections, setSections] = useState<ReportSection[]>(["overview", "indicators", "forecasts", "alerts"]);
  const [indicatorKeys, setIndicatorKeys] = useState("");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");

  const toggleSection = (key: ReportSection) => {
    setSections((current) =>
      current.includes(key) ? current.filter((s) => s !== key) : [...current, key],
    );
  };

  const submit = async () => {
    const payload: ReportInput = {
      kind,
      format,
      include_sections: sections,
    };
    if (title.trim()) payload.title = title.trim();
    if (note.trim()) payload.note = note.trim();
    if (studyAreaId) payload.study_area_id = Number(studyAreaId);
    if (kind === "periodic") {
      payload.period_type = periodType;
    } else {
      if (!customStart || !customEnd) {
        onError("A custom report needs both a period start and end date.");
        return;
      }
      if (customEnd < customStart) {
        onError("The period end must not be before the period start.");
        return;
      }
      payload.period_start = customStart;
      payload.period_end = customEnd;
    }
    const keys = indicatorKeys
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    if (keys.length > 0) payload.indicator_keys = keys;

    try {
      const created = await create.mutateAsync(payload);
      onDone(`Queued ${created.kind} report #${created.id} (${created.format.toUpperCase()}).`);
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "Could not queue the report.");
    }
  };

  return (
    <Card className="mb-5">
      <CardHeader
        title="New report"
        description="Periodic reports derive their window from a calendar preset (ending today). Reports only summarise what the platform has computed; indicator statistics are build-time summary statistics, not forecasts."
      />
      <form
        className="grid gap-4 px-5 py-4 sm:grid-cols-2 lg:grid-cols-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Field label="Kind" htmlFor="rp-kind" required>
          <Select
            id="rp-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as "periodic" | "custom")}
          >
            <option value="periodic">Periodic</option>
            <option value="custom">Custom period</option>
          </Select>
        </Field>

        {kind === "periodic" ? (
          <Field label="Period type" htmlFor="rp-period" required>
            <Select
              id="rp-period"
              value={periodType}
              onChange={(e) => setPeriodType(e.target.value as ReportPeriodType)}
            >
              {PERIOD_TYPES.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </Select>
          </Field>
        ) : (
          <>
            <Field label="From" htmlFor="rp-start" required>
              <TextInput
                id="rp-start"
                type="date"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
              />
            </Field>
            <Field label="To" htmlFor="rp-end" required>
              <TextInput
                id="rp-end"
                type="date"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
              />
            </Field>
          </>
        )}

        <Field label="Format" htmlFor="rp-format" required>
          <Select
            id="rp-format"
            value={format}
            onChange={(e) => setFormat(e.target.value as ReportFormat)}
          >
            <option value="pdf">PDF</option>
            <option value="csv">CSV</option>
          </Select>
        </Field>

        <Field label="Study area" htmlFor="rp-area" hint="Optional. Empty covers all study areas.">
          <Select
            id="rp-area"
            value={studyAreaId}
            onChange={(e) => setStudyAreaId(e.target.value)}
          >
            <option value="">All study areas</option>
            {(studyAreas.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        </Field>

        <Field
          label="Indicator keys"
          htmlFor="rp-keys"
          hint="Comma separated. Optional filter for the statistics section."
        >
          <TextInput
            id="rp-keys"
            value={indicatorKeys}
            placeholder='e.g. water_level_altimetry, turbidity_proxy'
            onChange={(e) => setIndicatorKeys(e.target.value)}
          />
        </Field>

        <Field label="Title" htmlFor="rp-title" hint="Optional; generated when empty.">
          <TextInput
            id="rp-title"
            value={title}
            maxLength={220}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>

        <Field label="Note" htmlFor="rp-note" hint="Optional context recorded on the report.">
          <TextArea id="rp-note" value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
        </Field>

        <div className="sm:col-span-2 lg:col-span-3">
          <p className="mb-2 text-xs font-medium text-muted">Sections to include</p>
          <div className="flex flex-wrap gap-2">
            {SECTIONS.map((section) => (
              <label
                key={section.key}
                className={
                  sections.includes(section.key)
                    ? "flex items-center gap-2 rounded-md border border-brand/40 bg-brand-light px-3 py-1.5 text-xs text-brand-dark"
                    : "flex items-center gap-2 rounded-md border border-line px-3 py-1.5 text-xs text-muted"
                }
              >
                <input
                  type="checkbox"
                  className="accent-[var(--color-brand)]"
                  checked={sections.includes(section.key)}
                  onChange={() => toggleSection(section.key)}
                />
                {section.label}
              </label>
            ))}
          </div>
        </div>

        <div className="text-xs text-muted sm:col-span-2 lg:col-span-3">
          <FileText size={13} className="mr-1 inline" />
          Content honesty: “Indicator statistics” are summary statistics (count, min, mean, max,
          first, last, quality flags) computed from stored results when the report is built. There
          is no statistics or ML module; nothing in the report predicts the future. Proxy indicators
          are flagged as unvalidated remote-sensing estimates.
        </div>

        <div className="sm:col-span-2 lg:col-span-3">
          <Button type="submit" loading={create.isPending}>
            <FileText size={16} /> Build report
          </Button>
        </div>
      </form>
    </Card>
  );
}
