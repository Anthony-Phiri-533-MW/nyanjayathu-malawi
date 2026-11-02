import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextInput } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingRows } from "@/components/ui/States";
import { Table, Td, Th, Tr } from "@/components/ui/Table";
import { ApiError } from "@/lib/api";
import {
  useComparePeriods,
  useIndicatorDefinitions,
  useStudyAreas,
  useTimeSeries,
} from "@/lib/hooks";
import { flagStyle, formatDate, formatNumber } from "@/lib/format";
import type { Comparison } from "@/lib/types";

/** Charts use the primary water hue so series read consistently across the app. */
const SERIES_COLOR = "#1d5fa8";

export function AnalysisPage() {
  const definitions = useIndicatorDefinitions();
  const studyAreas = useStudyAreas();
  const [indicatorKey, setIndicatorKey] = useState("");
  const [areaId, setAreaId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  const defaultArea = studyAreas.data?.find((a) => a.is_default) ?? studyAreas.data?.[0];
  const effectiveArea = areaId ? Number(areaId) : defaultArea?.id;
  const definition = (definitions.data ?? []).find((d) => d.key === indicatorKey);

  const timeseries = useTimeSeries(
    {
      indicator_key: indicatorKey,
      study_area_id: effectiveArea,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
    },
    { enabled: Boolean(indicatorKey) },
  );

  const points = timeseries.data?.points ?? [];
  const validPoints = points.filter((p) => p.value !== null);
  const chartData = validPoints.map((p) => ({ date: p.date, value: p.value }));

  return (
    <div>
      <PageHeader
        title="Analysis"
        description="Explore indicator time series and compare two periods. Points carrying a quality flag are shown but should be read with their reason attached; excluded points are counted rather than silently dropped."
      />

      <Card className="mb-5">
        <CardBody className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Indicator" htmlFor="an-indicator" required>
            <Select
              id="an-indicator"
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
          <Field label="Study area" htmlFor="an-area">
            <Select id="an-area" value={areaId} onChange={(e) => setAreaId(e.target.value)}>
              <option value="">
                Default{defaultArea ? ` (${defaultArea.name})` : ""}
              </option>
              {(studyAreas.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="From" htmlFor="an-from">
            <TextInput
              id="an-from"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </Field>
          <Field label="To" htmlFor="an-to">
            <TextInput
              id="an-to"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </Field>
        </CardBody>
      </Card>

      {!indicatorKey ? (
        <Card>
          <EmptyState
            title="Choose an indicator"
            description="Select an indicator above to plot its time series."
          />
        </Card>
      ) : timeseries.isLoading ? (
        <Card>
          <LoadingRows rows={5} />
        </Card>
      ) : timeseries.isError ? (
        <Card>
          <ErrorState error={timeseries.error} onRetry={() => timeseries.refetch()} />
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader
              title={timeseries.data?.indicator_name ?? "Time series"}
              description={
                `${validPoints.length} usable point(s)` +
                (timeseries.data?.excluded_points
                  ? ` · ${timeseries.data.excluded_points} excluded`
                  : "") +
                (definition?.is_proxy ? " · proxy indicator (unvalidated)" : "")
              }
              actions={
                <Badge className="bg-canvas text-muted">{timeseries.data?.unit || "—"}</Badge>
              }
            />
            <CardBody>
              {chartData.length > 0 ? (
                <div className="h-80 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e5ea" />
                      <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#6b7280" }} minTickGap={24} />
                      <YAxis
                        tick={{ fontSize: 11, fill: "#6b7280" }}
                        width={64}
                        domain={["auto", "auto"]}
                      />
                      <Tooltip
                        contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: "#e2e5ea" }}
                        formatter={(value: number) => [
                          formatNumber(value, { unit: timeseries.data?.unit }),
                          timeseries.data?.indicator_name ?? "value",
                        ]}
                      />
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke={SERIES_COLOR}
                        strokeWidth={2}
                        dot={{ r: 2.5, fill: SERIES_COLOR }}
                        connectNulls={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState
                  title="No usable points in this range"
                  description="Try widening the dates, or compute the indicator first."
                />
              )}

              {points.length > 0 ? (
                <div className="mt-4 max-h-64 overflow-y-auto rounded border border-border">
                  <Table>
                    <thead>
                      <tr>
                        <Th>Date</Th>
                        <Th align="right">Value</Th>
                        <Th>Flag</Th>
                        <Th>Source</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {points.map((p) => {
                        const style = flagStyle(p.quality_flag);
                        return (
                          <Tr key={`${p.date}-${p.result_id}`}>
                            <Td className="whitespace-nowrap text-xs">{formatDate(p.date)}</Td>
                            <Td align="right">
                              {p.value === null ? (
                                <span className="italic text-muted">not computed</span>
                              ) : (
                                formatNumber(p.value)
                              )}
                            </Td>
                            <Td>
                              <Badge className={style.className} title={p.quality_reason}>
                                {style.label}
                              </Badge>
                            </Td>
                            <Td className="text-xs text-muted">{p.dataset_title ?? "—"}</Td>
                          </Tr>
                        );
                      })}
                    </tbody>
                  </Table>
                </div>
              ) : null}

              {timeseries.data?.limitations ? (
                <p className="mt-3 text-xs text-muted">{timeseries.data.limitations}</p>
              ) : null}
            </CardBody>
          </Card>

          <ComparisonCard
            indicatorKey={indicatorKey}
            indicatorName={definition?.name ?? indicatorKey}
            studyAreaId={effectiveArea ?? null}
          />
        </>
      )}
    </div>
  );
}

function ComparisonCard({
  indicatorKey,
  indicatorName,
  studyAreaId,
}: {
  indicatorKey: string;
  indicatorName: string;
  studyAreaId: number | null;
}) {
  const compare = useComparePeriods();
  const [aStart, setAStart] = useState("");
  const [aEnd, setAEnd] = useState("");
  const [bStart, setBStart] = useState("");
  const [bEnd, setBEnd] = useState("");
  const [aggregation, setAggregation] = useState("mean");
  const [result, setResult] = useState<Comparison | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setError(null);
    setResult(null);
    if (!studyAreaId) {
      setError("Choose a study area first.");
      return;
    }
    if (!aStart || !aEnd || !bStart || !bEnd) {
      setError("Fill in both periods (start and end for A and B).");
      return;
    }
    try {
      const comparison = await compare.mutateAsync({
        study_area_id: studyAreaId,
        indicator_keys: [indicatorKey],
        period_a: { start: aStart, end: aEnd },
        period_b: { start: bStart, end: bEnd },
        aggregation,
      });
      setResult(comparison);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Comparison failed.");
    }
  };

  return (
    <Card className="mt-5">
      <CardHeader
        title="Compare two periods"
        description="Aggregates each period separately, then reports the direction and size of change. Incompatible coverage is flagged rather than compared blindly."
      />
      <CardBody>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-md border border-water-200 bg-water-50/40 p-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-water-700">
              Period A
            </p>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Start" htmlFor="cmp-a-start">
                <TextInput id="cmp-a-start" type="date" value={aStart} onChange={(e) => setAStart(e.target.value)} />
              </Field>
              <Field label="End" htmlFor="cmp-a-end">
                <TextInput id="cmp-a-end" type="date" value={aEnd} onChange={(e) => setAEnd(e.target.value)} />
              </Field>
            </div>
          </div>
          <div className="rounded-md border border-signal-200 bg-signal-50/50 p-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-signal-700">
              Period B
            </p>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Start" htmlFor="cmp-b-start">
                <TextInput id="cmp-b-start" type="date" value={bStart} onChange={(e) => setBStart(e.target.value)} />
              </Field>
              <Field label="End" htmlFor="cmp-b-end">
                <TextInput id="cmp-b-end" type="date" value={bEnd} onChange={(e) => setBEnd(e.target.value)} />
              </Field>
            </div>
          </div>
        </div>

        <Field label="Aggregation" htmlFor="cmp-agg" className="mt-4 max-w-xs">
          <Select id="cmp-agg" value={aggregation} onChange={(e) => setAggregation(e.target.value)}>
            <option value="mean">Mean</option>
            <option value="median">Median</option>
            <option value="min">Minimum</option>
            <option value="max">Maximum</option>
          </Select>
        </Field>

        {error ? <p className="mt-3 text-sm text-danger-dark">{error}</p> : null}

        <Button className="mt-4" loading={compare.isPending} onClick={() => void run()}>
          Compare periods
        </Button>

        {result ? (
          <div className="mt-5">
            <p className="text-sm text-muted">{result.limitations}</p>
            <Table className="mt-3">
              <thead>
                <tr>
                  <Th>Indicator</Th>
                  <Th align="right">Period A</Th>
                  <Th align="right">Period B</Th>
                  <Th align="right">Δ</Th>
                  <Th align="right">Δ %</Th>
                  <Th>Compatibility</Th>
                </tr>
              </thead>
              <tbody>
                {result.entries.map((entry) => (
                  <Tr key={entry.indicator_key}>
                    <Td>
                      <p className="font-medium text-ink">{entry.indicator_name || indicatorName}</p>
                      <p className="text-xs text-muted">
                        {entry.aggregation} · {entry.unit || "—"}
                      </p>
                    </Td>
                    <Td align="right">
                      {entry.a.value === null ? (
                        <span className="italic text-muted">not computed</span>
                      ) : (
                        formatNumber(entry.a.value)
                      )}
                      <p className="text-xs text-muted">{entry.a.sample_count} pt(s)</p>
                    </Td>
                    <Td align="right">
                      {entry.b.value === null ? (
                        <span className="italic text-muted">not computed</span>
                      ) : (
                        formatNumber(entry.b.value)
                      )}
                      <p className="text-xs text-muted">{entry.b.sample_count} pt(s)</p>
                    </Td>
                    <Td align="right">{entry.delta === null ? "—" : formatNumber(entry.delta)}</Td>
                    <Td align="right">
                      {entry.delta_percent === null ? "—" : `${entry.delta_percent.toFixed(1)}%`}
                    </Td>
                    <Td>
                      <Badge
                        className={
                          entry.compatible
                            ? "bg-success-light text-success-dark"
                            : "bg-warning-light text-warning-dark"
                        }
                      >
                        {entry.compatible ? "Comparable" : "Check coverage"}
                      </Badge>
                      {entry.notes ? <p className="mt-1 text-xs text-muted">{entry.notes}</p> : null}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
