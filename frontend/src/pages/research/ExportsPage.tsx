import { useState } from "react";
import { Download, FileDown } from "lucide-react";
import { useAuth } from "@/auth/AuthContext";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextInput } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError, downloadUrl } from "@/lib/api";
import { useCreateExport, useExports, useIndicatorDefinitions, useStudyAreas } from "@/lib/hooks";
import { formatBytes, formatDateTime, statusStyle, titleCase } from "@/lib/format";
import type { ExportFormat, ExportResource } from "@/lib/types";

/**
 * Which formats each resource supports. `raster` copies a GeoTIFF unchanged or
 * writes a statistics summary, so GeoJSON makes no sense there; the tabular
 * resources have no raster form. Mirrors `EXPORT_RESOURCES`/`EXTENSIONS` on the
 * backend, and the API rejects anything else rather than guessing.
 */
const FORMATS_BY_RESOURCE: Record<ExportResource, ExportFormat[]> = {
  datasets: ["csv", "json", "geojson"],
  indicator_results: ["csv", "json", "geojson"],
  timeseries: ["csv", "json"],
  comparison: ["csv", "json"],
  raster: ["geotiff", "json"],
};

const RESOURCE_HELP: Record<ExportResource, string> = {
  datasets: "Dataset metadata and quality flags. GeoJSON carries the recorded coverage footprints.",
  indicator_results: "Computed indicator values with unit, coverage and flag reason.",
  timeseries: "One row per point in a single indicator series. Requires an indicator.",
  comparison: "A two-period comparison table. Requires both periods and an indicator.",
  raster: "The stored GeoTIFF for one dataset or derived product, or a JSON band-statistics summary.",
};

export function ExportsPage() {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const [banner, setBanner] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const exports = useExports({ page, size: 20 });
  const canCreate = can("research.exports.create");
  const canDownload = can("research.exports.download");

  return (
    <div>
      <PageHeader
        title="Exports"
        description="Generate downloadable research outputs. Exports run as background jobs and keep a record of the exact filters used, so a file can be reproduced later."
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
        <ExportForm
          onDone={(message) => setBanner({ tone: "ok", text: message })}
          onError={(text) => setBanner({ tone: "error", text })}
        />
      ) : (
        <Card className="mb-5">
          <CardBody>
            <p className="text-sm text-muted">
              You have read access to export records but not permission to create new ones.
            </p>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Export history"
          description={`${exports.data?.total ?? 0} export(s). A file becomes downloadable once its job succeeds.`}
          actions={
            <Button variant="secondary" size="sm" onClick={() => exports.refetch()}>
              Refresh
            </Button>
          }
        />
        {exports.isLoading ? (
          <LoadingRows rows={5} />
        ) : exports.isError ? (
          <ErrorState error={exports.error} onRetry={() => exports.refetch()} />
        ) : exports.data && exports.data.items.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Export</Th>
                  <Th>Status</Th>
                  <Th>Size</Th>
                  <Th>Created</Th>
                  <Th align="right">File</Th>
                </tr>
              </thead>
              <tbody>
                {exports.data.items.map((record) => {
                  const jobStatus = record.job?.status ?? "pending";
                  const ready =
                    jobStatus === "succeeded" && Boolean(record.file_name) && canDownload;
                  return (
                    <Tr key={record.id}>
                      <Td>
                        <p className="font-medium text-ink">
                          #{record.id} · {titleCase(record.resource_type)}
                        </p>
                        <p className="text-xs text-muted">
                          {record.format.toUpperCase()} ·{" "}
                          {Object.entries((record.params?.filters as Record<string, unknown>) ?? {})
                            .map(([k, v]) => `${k}=${String(v)}`)
                            .join(", ") || "no filters"}
                        </p>
                      </Td>
                      <Td>
                        <Badge className={statusStyle(jobStatus)}>{jobStatus}</Badge>
                        {record.job?.error ? (
                          <p className="mt-1 max-w-xs text-xs text-danger">{record.job.error}</p>
                        ) : null}
                      </Td>
                      <Td align="right">{formatBytes(record.size_bytes)}</Td>
                      <Td className="whitespace-nowrap text-xs">
                        {formatDateTime(record.created_at)}
                      </Td>
                      <Td align="right">
                        {ready ? (
                          <a
                            className="btn-secondary inline-flex items-center gap-1 px-2.5 py-1 text-xs"
                            href={downloadUrl(`/exports/${record.id}/download`)}
                          >
                            <Download size={13} /> Download
                          </a>
                        ) : (
                          <span className="text-xs text-muted">
                            {jobStatus === "succeeded" ? "Ready" : "Pending"}
                          </span>
                        )}
                      </Td>
                    </Tr>
                  );
                })}
              </tbody>
            </Table>
            <Pagination
              page={exports.data.page}
              pages={exports.data.pages}
              total={exports.data.total}
              onChange={setPage}
            />
          </>
        ) : (
          <EmptyState
            title="No exports yet"
            description="Create an export above to produce a downloadable file."
          />
        )}
      </Card>
    </div>
  );
}

function ExportForm({
  onDone,
  onError,
}: {
  onDone: (message: string) => void;
  onError: (text: string) => void;
}) {
  const create = useCreateExport();
  const studyAreas = useStudyAreas();
  const definitions = useIndicatorDefinitions();

  const [resource, setResource] = useState<ExportResource>("datasets");
  const [format, setFormat] = useState<ExportFormat>("csv");
  const [studyAreaId, setStudyAreaId] = useState("");
  const [indicatorKey, setIndicatorKey] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [datasetIds, setDatasetIds] = useState("");
  // Comparison needs two windows; kept as the same JSON shape the API expects.
  const [aStart, setAStart] = useState("");
  const [aEnd, setAEnd] = useState("");
  const [bStart, setBStart] = useState("");
  const [bEnd, setBEnd] = useState("");
  const [aggregation, setAggregation] = useState("mean");

  const formats = FORMATS_BY_RESOURCE[resource];
  const needsIndicator = resource === "timeseries" || resource === "comparison";
  const needsDataset = resource === "raster";

  const changeResource = (next: ExportResource) => {
    setResource(next);
    // Keep the format valid for the newly chosen resource.
    if (!FORMATS_BY_RESOURCE[next].includes(format)) {
      setFormat(FORMATS_BY_RESOURCE[next][0]);
    }
  };

  const submit = async () => {
    const filters: Record<string, unknown> = {};
    if (studyAreaId) filters.study_area_id = Number(studyAreaId);
    if (startDate) filters.start_date = startDate;
    if (endDate) filters.end_date = endDate;

    if (needsIndicator) {
      if (!indicatorKey) {
        onError("Choose an indicator for this export.");
        return;
      }
      filters.indicator_key = indicatorKey;
      filters.indicator_keys = [indicatorKey];
      if (resource === "timeseries") filters.aggregation = aggregation;
    }
    if (resource === "comparison") {
      if (!studyAreaId || !aStart || !aEnd || !bStart || !bEnd) {
        onError("A comparison export needs a study area and both period windows.");
        return;
      }
      filters.period_a = { start: aStart, end: aEnd };
      filters.period_b = { start: bStart, end: bEnd };
      filters.aggregation = aggregation;
    }
    if (needsDataset) {
      const ids = datasetIds
        .split(",")
        .map((v) => Number(v.trim()))
        .filter((v) => Number.isFinite(v) && v > 0);
      if (ids.length === 0) {
        onError("Enter at least one dataset ID for a raster export.");
        return;
      }
      filters.dataset_id = ids[0];
    }

    try {
      const created = await create.mutateAsync({ resource, format, filters });
      onDone(`Queued export #${created.id} (${resource} → ${format}).`);
    } catch (error) {
      onError(error instanceof ApiError ? error.message : "Could not queue the export.");
    }
  };

  return (
    <Card className="mb-5">
      <CardHeader
        title="New export"
        description="Pick what to export and in which format. The job records the filters it ran with."
      />
      <form
        className="grid gap-4 px-5 py-4 sm:grid-cols-2 lg:grid-cols-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Field label="Resource" htmlFor="ex-resource" required>
          <Select
            id="ex-resource"
            value={resource}
            onChange={(e) => changeResource(e.target.value as ExportResource)}
          >
            {(Object.keys(FORMATS_BY_RESOURCE) as ExportResource[]).map((r) => (
              <option key={r} value={r}>
                {titleCase(r)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Format" htmlFor="ex-format" required>
          <Select
            id="ex-format"
            value={format}
            onChange={(e) => setFormat(e.target.value as ExportFormat)}
          >
            {formats.map((f) => (
              <option key={f} value={f}>
                {f.toUpperCase()}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Study area" htmlFor="ex-area" hint="Optional for most resources.">
          <Select
            id="ex-area"
            value={studyAreaId}
            onChange={(e) => setStudyAreaId(e.target.value)}
          >
            <option value="">All / default</option>
            {(studyAreas.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        </Field>

        {needsIndicator ? (
          <Field label="Indicator" htmlFor="ex-indicator" required>
            <Select
              id="ex-indicator"
              value={indicatorKey}
              onChange={(e) => setIndicatorKey(e.target.value)}
            >
              <option value="">Select…</option>
              {(definitions.data ?? []).map((d) => (
                <option key={d.key} value={d.key}>
                  {d.name}
                </option>
              ))}
            </Select>
          </Field>
        ) : null}

        {resource === "comparison" || resource === "timeseries" ? (
          <Field label="Aggregation" htmlFor="ex-agg">
            <Select id="ex-agg" value={aggregation} onChange={(e) => setAggregation(e.target.value)}>
              <option value="mean">Mean</option>
              <option value="median">Median</option>
              <option value="min">Minimum</option>
              <option value="max">Maximum</option>
            </Select>
          </Field>
        ) : null}

        {needsDataset ? (
          <Field
            label="Dataset IDs"
            htmlFor="ex-datasets"
            hint="Comma separated. Only the first ID is used for a raster export."
            required
          >
            <TextInput
              id="ex-datasets"
              value={datasetIds}
              placeholder="e.g. 12"
              onChange={(e) => setDatasetIds(e.target.value)}
            />
          </Field>
        ) : (
          <>
            <Field label="From" htmlFor="ex-start" hint="Optional date bound.">
              <TextInput
                id="ex-start"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </Field>
            <Field label="To" htmlFor="ex-end">
              <TextInput
                id="ex-end"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </Field>
          </>
        )}

        {resource === "comparison" ? (
          <div className="grid gap-3 sm:col-span-2 lg:col-span-3 lg:grid-cols-4">
            <Field label="Period A start" htmlFor="ex-a-start" required>
              <TextInput id="ex-a-start" type="date" value={aStart} onChange={(e) => setAStart(e.target.value)} />
            </Field>
            <Field label="Period A end" htmlFor="ex-a-end" required>
              <TextInput id="ex-a-end" type="date" value={aEnd} onChange={(e) => setAEnd(e.target.value)} />
            </Field>
            <Field label="Period B start" htmlFor="ex-b-start" required>
              <TextInput id="ex-b-start" type="date" value={bStart} onChange={(e) => setBStart(e.target.value)} />
            </Field>
            <Field label="Period B end" htmlFor="ex-b-end" required>
              <TextInput id="ex-b-end" type="date" value={bEnd} onChange={(e) => setBEnd(e.target.value)} />
            </Field>
          </div>
        ) : null}

        <div className="text-xs text-muted sm:col-span-2 lg:col-span-3">
          {RESOURCE_HELP[resource]}
        </div>

        <div className="sm:col-span-2 lg:col-span-3">
          <Button type="submit" loading={create.isPending}>
            <FileDown size={16} /> Queue export
          </Button>
        </div>
      </form>
    </Card>
  );
}
