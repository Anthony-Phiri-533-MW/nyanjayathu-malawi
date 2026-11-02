import { useMemo, useState } from "react";
import { Calculator, Info } from "lucide-react";
import { PageHeader, ProvisionalNote } from "@/components/PageHeader";
import { Badge, Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Checkbox, Field, Select, TextInput } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Pagination, Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError } from "@/lib/api";
import {
  useComputeIndicators,
  useIndicatorDefinitions,
  useIndicatorResults,
  useQualityFlags,
  useStudyAreas,
} from "@/lib/hooks";
import { flagStyle, formatDate, formatDateTime, formatNumber } from "@/lib/format";

export function IndicatorsPage() {
  const [page, setPage] = useState(1);
  const [filterKey, setFilterKey] = useState("");
  const [filterFlag, setFilterFlag] = useState("");
  const [filterArea, setFilterArea] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const definitions = useIndicatorDefinitions();
  const flags = useQualityFlags();
  const studyAreas = useStudyAreas();
  const results = useIndicatorResults({
    indicator_key: filterKey || undefined,
    quality_flag: filterFlag || undefined,
    study_area_id: filterArea ? Number(filterArea) : undefined,
    page,
    size: 20,
  });

  const resetPage = () => setPage(1);

  return (
    <div>
      <PageHeader
        title="Indicators"
        description="Computed water-level and water-quality indicators. Each result states its unit, temporal coverage, quality flag and method version. A null value means the indicator could not be computed — it is never reported as zero."
      />

      <ComputeCard definitions={definitions.data ?? []} areas={studyAreas.data ?? []} />

      <Card className="mt-6">
        <CardHeader
          title="Indicator results"
          description={`${results.data?.total ?? 0} result(s)`}
          actions={
            <div className="flex gap-2">
              <Select
                className="w-44"
                value={filterKey}
                onChange={(e) => {
                  setFilterKey(e.target.value);
                  resetPage();
                }}
              >
                <option value="">All indicators</option>
                {(definitions.data ?? []).map((d) => (
                  <option key={d.key} value={d.key}>
                    {d.name}
                  </option>
                ))}
              </Select>
              <Select
                className="w-40"
                value={filterFlag}
                onChange={(e) => {
                  setFilterFlag(e.target.value);
                  resetPage();
                }}
              >
                <option value="">All flags</option>
                {(flags.data?.flags ?? []).map((f) => (
                  <option key={f} value={f}>
                    {flagStyle(f).label}
                  </option>
                ))}
              </Select>
              <Select
                className="w-40"
                value={filterArea}
                onChange={(e) => {
                  setFilterArea(e.target.value);
                  resetPage();
                }}
              >
                <option value="">All areas</option>
                {(studyAreas.data ?? []).map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            </div>
          }
        />
        {results.isLoading ? (
          <LoadingRows rows={6} />
        ) : results.isError ? (
          <ErrorState error={results.error} onRetry={() => results.refetch()} />
        ) : results.data && results.data.items.length > 0 ? (
          <>
            <Table>
              <thead>
                <tr>
                  <Th>Indicator</Th>
                  <Th align="right">Value</Th>
                  <Th>Period</Th>
                  <Th>Quality</Th>
                  <Th align="right" />
                </tr>
              </thead>
              <tbody>
                {results.data.items.map((r) => {
                  const style = flagStyle(r.quality_flag);
                  const definition = (definitions.data ?? []).find((d) => d.key === r.indicator_key);
                  return (
                    <>
                      <Tr key={r.id}>
                        <Td>
                          <p className="font-medium text-ink">
                            {definition?.name ?? r.indicator_key}
                          </p>
                          <p className="text-xs text-muted">
                            {r.indicator_key} · {r.temporal_resolution}
                            {r.study_area_name ? ` · ${r.study_area_name}` : ""}
                          </p>
                        </Td>
                        <Td align="right">
                          {r.value === null ? (
                            <span className="text-sm italic text-muted">not computed</span>
                          ) : (
                            <span className="text-sm font-medium text-ink">
                              {formatNumber(r.value, { unit: r.unit })}
                            </span>
                          )}
                        </Td>
                        <Td className="whitespace-nowrap text-xs">
                          <p>{formatDate(r.observed_start)}</p>
                          <p className="text-muted">{formatDate(r.observed_end)}</p>
                          {r.coverage_fraction != null ? (
                            <p className="text-muted">coverage {(r.coverage_fraction * 100).toFixed(0)}%</p>
                          ) : null}
                        </Td>
                        <Td>
                          <Badge className={style.className} title={style.help}>
                            {style.label}
                          </Badge>
                          <p className="mt-1 max-w-xs text-xs text-muted">{r.quality_reason}</p>
                        </Td>
                        <Td align="right">
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                          >
                            {expanded === r.id ? "Hide" : "Detail"}
                          </Button>
                        </Td>
                      </Tr>
                      {expanded === r.id ? (
                        <tr key={`${r.id}-detail`}>
                          <td colSpan={5} className="border-b border-border bg-canvas px-4 py-3">
                            <div className="grid gap-4 sm:grid-cols-2">
                              <div>
                                <p className="text-xs font-semibold uppercase tracking-wide text-muted">
                                  Method
                                </p>
                                <p className="mt-1 text-sm text-ink-soft">
                                  {definition?.method || "—"} (v{definition?.method_version || "?"})
                                </p>
                                {definition?.is_proxy ? (
                                  <p className="mt-1 text-xs text-signal-700">
                                    Proxy method — indicative only.
                                  </p>
                                ) : null}
                                <p className="mt-2 text-xs text-muted">{definition?.definition}</p>
                              </div>
                              <div>
                                <p className="text-xs font-semibold uppercase tracking-wide text-muted">
                                  Provenance
                                </p>
                                <pre className="mt-1 max-h-40 overflow-auto rounded bg-surface p-2 text-xs text-ink-soft">
                                  {JSON.stringify(
                                    {
                                      dataset: r.dataset_title,
                                      product_id: r.product_id,
                                      job_id: r.job_id,
                                      parameters: r.parameters,
                                      uncertainty: r.uncertainty,
                                      flags: r.flag_reasons,
                                    },
                                    null,
                                    2,
                                  )}
                                </pre>
                                <p className="mt-1 text-xs text-muted">
                                  Computed {formatDateTime(r.created_at)}
                                </p>
                              </div>
                            </div>
                          </td>
                        </tr>
                      ) : null}
                    </>
                  );
                })}
              </tbody>
            </Table>
            <Pagination
              page={results.data.page}
              pages={results.data.pages}
              total={results.data.total}
              onChange={setPage}
            />
          </>
        ) : (
          <EmptyState
            title="No indicator results"
            description="Queue an indicator computation, or adjust the filters."
          />
        )}
      </Card>
    </div>
  );
}

function ComputeCard({
  definitions,
  areas,
}: {
  definitions: Array<{ key: string; name: string; is_proxy: boolean; unit: string; category: string }>;
  areas: Array<{ id: number; name: string; is_default: boolean }>;
}) {
  const compute = useComputeIndicators();
  const [selected, setSelected] = useState<string[]>([]);
  const [areaId, setAreaId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [banner, setBanner] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const defaultArea = areas.find((a) => a.is_default) ?? areas[0];
  const grouped = useMemo(() => {
    const map = new Map<string, typeof definitions>();
    for (const d of definitions) {
      const list = map.get(d.category) ?? [];
      list.push(d);
      map.set(d.category, list);
    }
    return Array.from(map.entries());
  }, [definitions]);

  const hasProxy = selected.some((key) => definitions.find((d) => d.key === key)?.is_proxy);

  return (
    <Card>
      <CardHeader
        title="Compute indicators"
        description="Choose one or more indicators and a study area. Missing prerequisites are computed automatically; incompatible inputs yield a null value with a reason."
      />
      <form
        className="grid gap-4 px-5 py-4 lg:grid-cols-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setBanner(null);
          if (selected.length === 0) {
            setBanner({ tone: "error", text: "Select at least one indicator." });
            return;
          }
          try {
            const job = await compute.mutateAsync({
              indicator_keys: selected,
              study_area_id: areaId ? Number(areaId) : (defaultArea?.id ?? null),
              start_date: startDate || null,
              end_date: endDate || null,
            });
            setBanner({
              tone: "ok",
              text: `Queued indicator job #${job.id}. Results appear below when it completes.`,
            });
            setSelected([]);
          } catch (error) {
            setBanner({
              tone: "error",
              text: error instanceof ApiError ? error.message : "Could not queue the job.",
            });
          }
        }}
      >
        <div className="lg:col-span-2">
          <p className="field-label">Indicators</p>
          <div className="space-y-3">
            {grouped.map(([category, items]) => (
              <div key={category}>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted">{category}</p>
                <div className="mt-1.5 flex flex-wrap gap-x-5 gap-y-2">
                  {items.map((d) => (
                    <Checkbox
                      key={d.key}
                      checked={selected.includes(d.key)}
                      onChange={() =>
                        setSelected((prev) =>
                          prev.includes(d.key) ? prev.filter((x) => x !== d.key) : [...prev, d.key],
                        )
                      }
                      label={
                        <span className="flex items-center gap-1.5">
                          {d.name}
                          {d.is_proxy ? (
                            <span
                              className="text-signal-700"
                              title="Proxy indicator — unvalidated for Lake Malawi"
                            >
                              <Info size={12} />
                            </span>
                          ) : null}
                        </span>
                      }
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-4">
          <Field label="Study area" htmlFor="ind-area">
            <Select
              id="ind-area"
              value={areaId}
              onChange={(e) => setAreaId(e.target.value)}
            >
              <option value="">
                Default area{defaultArea ? ` (${defaultArea.name})` : ""}
              </option>
              {areas.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Start date" htmlFor="ind-start" hint="Optional; limits which datasets are used.">
            <TextInput
              id="ind-start"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </Field>
          <Field label="End date" htmlFor="ind-end">
            <TextInput
              id="ind-end"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </Field>
        </div>

        {hasProxy ? (
          <div className="lg:col-span-3">
            <ProvisionalNote>
              One or more selected indicators are proxies (e.g. chlorophyll-a, turbidity). Their
              results are flagged UNVALIDATED until calibrated against in-situ measurements.
            </ProvisionalNote>
          </div>
        ) : null}

        {banner ? (
          <div
            className={
              banner.tone === "ok"
                ? "rounded-md border border-success/30 bg-success-light px-3 py-2 text-sm text-success-dark lg:col-span-3"
                : "rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-sm text-danger-dark lg:col-span-3"
            }
          >
            {banner.text}
          </div>
        ) : null}

        <div className="lg:col-span-3">
          <Button type="submit" loading={compute.isPending} disabled={selected.length === 0}>
            <Calculator size={16} /> Compute {selected.length > 0 ? `(${selected.length})` : ""}
          </Button>
        </div>
      </form>
    </Card>
  );
}
