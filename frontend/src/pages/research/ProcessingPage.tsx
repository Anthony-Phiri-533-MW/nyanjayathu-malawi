import { useState } from "react";
import { Play } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Checkbox, Field, Select, TextInput } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError } from "@/lib/api";
import {
  useCreateProcessingRun,
  useDatasets,
  useProcessingOperations,
  useProcessingRuns,
} from "@/lib/hooks";
import { formatDateTime, statusStyle } from "@/lib/format";

/**
 * Preprocessing. Operations are chained in the order they are ticked and are
 * applied to every selected input dataset. Each operation documents its own
 * assumptions; the cross-sensor adjustment is an identity transform unless
 * coefficients are supplied (see the operation description).
 */
export function ProcessingPage() {
  const [page, setPage] = useState(1);
  const [datasetSearch, setDatasetSearch] = useState("");
  const [selectedDatasets, setSelectedDatasets] = useState<number[]>([]);
  const [selectedOps, setSelectedOps] = useState<string[]>([]);
  const [params, setParams] = useState<Record<string, Record<string, string>>>({});
  const [outputName, setOutputName] = useState("");
  const [banner, setBanner] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const operations = useProcessingOperations();
  const datasets = useDatasets({ search: datasetSearch || undefined, page: 1, size: 50 });
  const runs = useProcessingRuns({ page, size: 15 });
  const createRun = useCreateProcessingRun();

  const toggleDataset = (id: number) =>
    setSelectedDatasets((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );

  const toggleOp = (key: string) =>
    setSelectedOps((prev) => (prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]));

  const moveOp = (key: string, direction: -1 | 1) => {
    setSelectedOps((prev) => {
      const index = prev.indexOf(key);
      if (index < 0) return prev;
      const next = [...prev];
      const target = index + direction;
      if (target < 0 || target >= next.length) return prev;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const opMap = new Map((operations.data ?? []).map((op) => [op.key, op]));

  const submit = async () => {
    setBanner(null);
    if (selectedDatasets.length === 0) {
      setBanner({ tone: "error", text: "Select at least one input dataset." });
      return;
    }
    if (selectedOps.length === 0) {
      setBanner({ tone: "error", text: "Select at least one operation." });
      return;
    }
    // Coerce parameter values to the declared JSON types before sending.
    const resolvedParams: Record<string, unknown> = {};
    for (const opKey of selectedOps) {
      const op = opMap.get(opKey);
      const values = params[opKey] ?? {};
      const opParams: Record<string, unknown> = {};
      for (const spec of op?.params ?? []) {
        const raw = values[spec.name];
        if (raw === undefined || raw === "") {
          opParams[spec.name] = spec.default;
          continue;
        }
        if (spec.type === "bool") opParams[spec.name] = raw === "true";
        else if (spec.type === "int") opParams[spec.name] = Number.parseInt(raw, 10);
        else if (spec.type === "float") opParams[spec.name] = Number.parseFloat(raw);
        else opParams[spec.name] = raw;
      }
      resolvedParams[opKey] = opParams;
    }

    try {
      const run = await createRun.mutateAsync({
        dataset_ids: selectedDatasets,
        operations: selectedOps,
        params: resolvedParams,
        output_name: outputName.trim(),
      });
      setBanner({
        tone: "ok",
        text: `Queued preprocessing run #${run.id} (${selectedOps.join(" → ")}).`,
      });
      setSelectedOps([]);
      setParams({});
      setOutputName("");
    } catch (error) {
      setBanner({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not queue the run.",
      });
    }
  };

  return (
    <div>
      <PageHeader
        title="Geospatial preprocessing"
        description="Chain the documented operations to prepare inputs for indicator computation. Operations are applied in order; each writes its own provenance record so a derived product can be traced back to its inputs."
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

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Input datasets"
            description={`${selectedDatasets.length} selected`}
            actions={
              <TextInput
                className="w-44"
                placeholder="Search"
                value={datasetSearch}
                onChange={(e) => setDatasetSearch(e.target.value)}
              />
            }
          />
          {datasets.isLoading ? (
            <LoadingRows rows={4} />
          ) : datasets.isError ? (
            <ErrorState error={datasets.error} onRetry={() => datasets.refetch()} />
          ) : datasets.data && datasets.data.items.length > 0 ? (
            <ul className="max-h-96 divide-y divide-border overflow-y-auto">
              {datasets.data.items.map((dataset) => (
                <li key={dataset.id} className="px-5 py-2.5">
                  <Checkbox
                    checked={selectedDatasets.includes(dataset.id)}
                    onChange={() => toggleDataset(dataset.id)}
                    label={
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-ink">{dataset.title}</span>
                        <Badge className={dataset.is_raw ? "bg-water-50 text-water-700" : "bg-signal-100 text-signal-700"}>
                          {dataset.is_raw ? "Observed" : "Derived"}
                        </Badge>
                      </span>
                    }
                  />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No datasets" description="Ingest data first." />
          )}
        </Card>

        <Card>
          <CardHeader
            title="Operations"
            description="Applied top to bottom. Use the arrows to reorder."
          />
          {operations.isLoading ? (
            <LoadingRows rows={4} />
          ) : operations.isError ? (
            <ErrorState error={operations.error} onRetry={() => operations.refetch()} />
          ) : (
            <>
              <ul className="max-h-72 divide-y divide-border overflow-y-auto">
                {(operations.data ?? []).map((op) => (
                  <li key={op.key} className="px-5 py-2.5">
                    <Checkbox
                      checked={selectedOps.includes(op.key)}
                      onChange={() => toggleOp(op.key)}
                      label={
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="font-medium text-ink">{op.label}</span>
                          {op.writes_product ? (
                            <Badge className="bg-signal-100 text-signal-700">Writes product</Badge>
                          ) : null}
                        </span>
                      }
                    />
                    <p className="ml-6 mt-0.5 text-xs text-muted">{op.description}</p>
                  </li>
                ))}
              </ul>

              {selectedOps.length > 0 ? (
                <CardBody className="border-t border-border">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Order</p>
                  <ol className="space-y-1">
                    {selectedOps.map((key, index) => (
                      <li key={key} className="flex items-center gap-2 text-sm">
                        <span className="tabular w-5 text-muted">{index + 1}.</span>
                        <span className="flex-1 text-ink-soft">{opMap.get(key)?.label ?? key}</span>
                        <button
                          type="button"
                          className="btn-secondary px-2 py-0.5 text-xs"
                          onClick={() => moveOp(key, -1)}
                          disabled={index === 0}
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          className="btn-secondary px-2 py-0.5 text-xs"
                          onClick={() => moveOp(key, 1)}
                          disabled={index === selectedOps.length - 1}
                        >
                          ↓
                        </button>
                      </li>
                    ))}
                  </ol>

                  {selectedOps.some((k) => (opMap.get(k)?.params.length ?? 0) > 0) ? (
                    <div className="mt-4 space-y-4 border-t border-border pt-4">
                      {selectedOps.map((key) => {
                        const op = opMap.get(key);
                        if (!op || op.params.length === 0) return null;
                        return (
                          <div key={key}>
                            <p className="text-xs font-semibold text-ink-soft">{op.label} parameters</p>
                            <div className="mt-2 grid gap-3 sm:grid-cols-2">
                              {op.params.map((spec) => (
                                <Field
                                  key={spec.name}
                                  label={spec.name.replace(/_/g, " ")}
                                  hint={spec.description}
                                >
                                  {spec.type === "bool" ? (
                                    <Select
                                      value={params[key]?.[spec.name] ?? String(spec.default ?? false)}
                                      onChange={(e) =>
                                        setParams((prev) => ({
                                          ...prev,
                                          [key]: { ...prev[key], [spec.name]: e.target.value },
                                        }))
                                      }
                                    >
                                      <option value="false">No</option>
                                      <option value="true">Yes</option>
                                    </Select>
                                  ) : (
                                    <TextInput
                                      type={spec.type === "string" ? "text" : "number"}
                                      step="any"
                                      value={params[key]?.[spec.name] ?? String(spec.default ?? "")}
                                      onChange={(e) =>
                                        setParams((prev) => ({
                                          ...prev,
                                          [key]: { ...prev[key], [spec.name]: e.target.value },
                                        }))
                                      }
                                    />
                                  )}
                                </Field>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}

                  <Field label="Output name" htmlFor="proc-name" className="mt-4" hint="Optional label for the derived product.">
                    <TextInput
                      id="proc-name"
                      value={outputName}
                      onChange={(e) => setOutputName(e.target.value)}
                    />
                  </Field>

                  <Button className="mt-4" loading={createRun.isPending} onClick={() => void submit()}>
                    <Play size={16} /> Queue preprocessing
                  </Button>
                </CardBody>
              ) : null}
            </>
          )}
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader title="Preprocessing runs" description="History of queued and completed runs." />
        {runs.isLoading ? (
          <LoadingRows rows={4} />
        ) : runs.isError ? (
          <ErrorState error={runs.error} onRetry={() => runs.refetch()} />
        ) : runs.data && runs.data.items.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Run</Th>
                  <Th>Operations</Th>
                  <Th>Status</Th>
                  <Th>Created</Th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((run) => (
                  <Tr key={run.id}>
                    <Td>
                      <p className="font-medium text-ink">#{run.id}</p>
                      <p className="text-xs text-muted">{run.operation}</p>
                    </Td>
                    <Td className="text-xs">
                      {(run.metrics?.operations as string[] | undefined)?.join(" → ") ??
                        run.operation}
                    </Td>
                    <Td>
                      <Badge className={statusStyle(run.status)}>{run.status}</Badge>
                      {run.error ? <p className="mt-1 text-xs text-danger">{run.error}</p> : null}
                    </Td>
                    <Td className="whitespace-nowrap text-xs">{formatDateTime(run.created_at)}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
            <Pagination
              page={runs.data.page}
              pages={runs.data.pages}
              total={runs.data.total}
              onChange={setPage}
            />
          </>
        ) : (
          <EmptyState title="No preprocessing runs yet" />
        )}
      </Card>
    </div>
  );
}
