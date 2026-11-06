import { useMemo, useState } from "react";
import { CloudRain, Gauge } from "lucide-react";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextArea, TextInput } from "@/components/ui/Field";
import { ErrorState, EmptyState, LoadingRows } from "@/components/ui/States";
import { PageHeader, ProvisionalNote } from "@/components/PageHeader";
import { LocalModelsPanel } from "@/components/LocalModelsPanel";
import {
  useCreateForecast,
  useForecasts,
  useIndicatorDefinitions,
  useMLModels,
  useModelEvaluations,
  useStudyAreas,
} from "@/lib/hooks";
import { formatDate, formatDateTime, formatNumber, titleCase } from "@/lib/format";
import { useAuth } from "@/auth/AuthContext";
import type { ModelEvaluation } from "@/lib/types";

const INDICATOR_OPTIONS = [
  "rainfall_summary",
  "rainfall_anomaly",
  "temperature_summary",
  "temperature_anomaly",
  "water_level_altimetry",
  "water_extent",
  "chlorophyll_a_proxy",
  "turbidity_proxy",
] as const;

function metric(n: number | null | undefined, digits = 3): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return formatNumber(n, { digits });
}

export function ForecastsPage() {
  const { can } = useAuth();
  const areas = useStudyAreas();
  const definitions = useIndicatorDefinitions();
  const forecasts = useForecasts({ size: 100 });
  const mlModels = useMLModels({ active_only: true, size: 50 });
  const evaluations = useModelEvaluations({ size: 100 });
  const create = useCreateForecast();

  const [form, setForm] = useState({
    indicator_key: "",
    study_area_id: "",
    target_date: "",
    value: "",
    unit: "",
    note: "",
  });
  const [submitted, setSubmitted] = useState(false);

  // Manual forecast recording is gated separately from threshold evaluation.
  const canRecordManual = can("disaster.forecasts.write") || can("disaster.evaluate.run");
  const canRunModels = can("research.forecasts.run");
  const set = (key: keyof typeof form) => (value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  const definitionUnit = (key: string): string => {
    const def = definitions.data?.find((d) => d.key === key);
    return def?.unit ?? "";
  };

  const optionForKey = (key: string): string => {
    if (key && definitionUnit(key) && !form.unit) {
      return definitionUnit(key);
    }
    return form.unit;
  };

  const handleSubmit = () => {
    setSubmitted(true);
    if (!form.indicator_key || !form.study_area_id || !form.target_date || !form.value || !form.note.trim()) {
      return;
    }
    create.mutate(
      {
        indicator_key: form.indicator_key,
        study_area_id: Number(form.study_area_id),
        target_date: form.target_date,
        value: Number(form.value),
        unit: optionForKey(form.indicator_key),
        note: form.note.trim(),
      },
      {
        onSuccess: () => {
          setForm((f) => ({ ...f, value: "", note: "", target_date: "" }));
          setSubmitted(false);
        },
      },
    );
  };

  const canSubmit =
    canRecordManual &&
    form.indicator_key &&
    form.study_area_id &&
    form.target_date &&
    form.value &&
    form.note.trim();

  const evalsByModel = useMemo(() => {
    const map = new Map<number, ModelEvaluation[]>();
    for (const e of evaluations.data?.items ?? []) {
      const list = map.get(e.model_id) ?? [];
      list.push(e);
      map.set(e.model_id, list);
    }
    return map;
  }, [evaluations.data]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Forecasts & model performance"
        description="Short-term forecasts are produced by the ML pipeline from stored indicator history (blocked rolling-origin validation). Disaster evaluation compares forecast/observed values against approved thresholds. Manual projections can be recorded with mandatory provenance."
      />

      <ProvisionalNote>
        Model-generated forecasts are estimates, not observations. RMSE/MAE/Bias below come from
        out-of-fold blocked validation (train before origin, test after) — never in-sample accuracy.
        Manual projections remain user-supplied and require a provenance note.
      </ProvisionalNote>

      <LocalModelsPanel canRun={canRunModels} />

      <Card>
        <CardHeader
          title="Active model performance"
          description={
            mlModels.data
              ? `${mlModels.data.total} active model(s). Metrics: out-of-fold blocked validation.`
              : undefined
          }
        />
        <CardBody>
          {mlModels.isLoading ? (
            <LoadingRows rows={4} />
          ) : mlModels.isError ? (
            <ErrorState error={mlModels.error} />
          ) : !mlModels.data?.items.length ? (
            <EmptyState
              title="No active forecast models"
              description="Models appear after the forecasting pipeline has enough indicator history (see forecast min points / blocked folds). Skipped runs produce no fabricated metrics."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Indicator / area</th>
                    <th>Algorithm</th>
                    <th>RMSE</th>
                    <th>MAE</th>
                    <th>Bias</th>
                    <th>Skill (vs persist.)</th>
                    <th>Training</th>
                    <th>Trained</th>
                  </tr>
                </thead>
                <tbody>
                  {mlModels.data.items.map((m) => {
                    const foldCount = evalsByModel.get(m.id)?.length;
                    return (
                      <tr key={m.id}>
                        <td>
                          <div className="font-medium text-ink">{titleCase(m.indicator_key)}</div>
                          <div className="text-xs text-muted">{m.study_area_name ?? m.study_area_id ?? "All areas"}</div>
                        </td>
                        <td className="text-ink-soft">
                          <Badge className="bg-water-50 text-water-800">{m.algorithm}</Badge>
                          {foldCount ? <span className="ml-2 text-xs text-muted">{foldCount} folds</span> : null}
                        </td>
                        <td className="tabular text-ink-soft">{metric(m.rmse)}</td>
                        <td className="tabular text-ink-soft">{metric(m.mae)}</td>
                        <td className="tabular text-ink-soft">{metric(m.bias)}</td>
                        <td className="tabular text-ink-soft">{metric(m.skill_score)}</td>
                        <td className="text-xs text-muted">
                          {m.n_train} pts · {m.cadence}
                          {m.train_start && m.train_end ? (
                            <div>{formatDate(m.train_start)}–{formatDate(m.train_end)}</div>
                          ) : null}
                        </td>
                        <td className="text-xs text-muted">{formatDateTime(m.trained_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {evaluations.data?.items.length ? (
            <details className="mt-4 rounded-md border border-border bg-canvas/50 p-3">
              <summary className="cursor-pointer text-sm font-medium text-ink-soft">
                Blocked-validation folds (RMSE / MAE / Bias per fold)
              </summary>
              <div className="mt-3 overflow-x-auto">
                <table className="table text-xs">
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th>Fold</th>
                      <th>Train → Test</th>
                      <th>RMSE</th>
                      <th>MAE</th>
                      <th>Bias</th>
                      <th>Coverage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evaluations.data.items.slice(0, 60).map((e) => (
                      <tr key={e.id}>
                        <td className="text-ink-soft">#{e.model_id} {titleCase(e.indicator_key)}</td>
                        <td>{e.fold}</td>
                        <td className="text-muted">
                          {e.train_end ? formatDate(e.train_end) : "?"} → {e.test_start ? formatDate(e.test_start) : "?"}
                          {e.test_end ? `–${formatDate(e.test_end)}` : ""}
                        </td>
                        <td className="tabular">{metric(e.rmse)}</td>
                        <td className="tabular">{metric(e.mae)}</td>
                        <td className="tabular">{metric(e.bias)}</td>
                        <td className="tabular">{e.coverage != null ? `${Math.round(e.coverage * 100)}%` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          ) : null}
        </CardBody>
      </Card>

      {canRecordManual ? (
        <Card>
          <CardHeader title="Record a manual projection (optional)" />
          <CardBody>
            <p className="mb-4 text-xs text-muted">
              Use this only for user-supplied/external projections. ML pipeline forecasts appear
              automatically below with source <span className="font-medium">model</span>. Manual
              recording requires <span className="font-medium">disaster.forecasts.write</span> (or
              legacy <span className="font-medium">disaster.evaluate.run</span>).
            </p>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              <Field
                label="Indicator"
                htmlFor="f-indicator"
                error={submitted && !form.indicator_key ? "Select an indicator" : undefined}
              >
                <Select
                  id="f-indicator"
                  value={form.indicator_key}
                  onChange={(e) => {
                    set("indicator_key")(e.target.value);
                    const def = definitions.data?.find((d) => d.key === e.target.value);
                    if (def?.unit) set("unit")(def.unit);
                  }}
                >
                  <option value="">Select an indicator…</option>
                  {INDICATOR_OPTIONS.map((k) => (
                    <option key={k} value={k}>
                      {definitions.data?.find((d) => d.key === k)?.name ?? k.replace(/_/g, " ")}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field
                label="Study area"
                htmlFor="f-area"
                error={submitted && !form.study_area_id ? "Select a study area" : undefined}
              >
                <Select
                  id="f-area"
                  value={form.study_area_id}
                  onChange={(e) => set("study_area_id")(e.target.value)}
                >
                  <option value="">Select a study area…</option>
                  {(areas.data ?? []).map((area) => (
                    <option key={area.id} value={String(area.id)}>
                      {area.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field
                label="Target date"
                htmlFor="target-date"
                error={submitted && !form.target_date ? "Target date is required" : undefined}
              >
                <TextInput
                  id="target-date"
                  type="date"
                  value={form.target_date}
                  onChange={(e) => set("target_date")(e.target.value)}
                />
              </Field>
              <Field
                label="Value"
                htmlFor="f-value"
                error={submitted && !form.value ? "Value is required" : undefined}
              >
                <TextInput
                  id="f-value"
                  type="number"
                  step="any"
                  value={form.value}
                  onChange={(e) => set("value")(e.target.value)}
                />
              </Field>
              <Field label="Unit" htmlFor="f-unit" hint="Prefilled from the indicator definition.">
                <TextInput
                  id="f-unit"
                  value={form.unit}
                  onChange={(e) => set("unit")(e.target.value)}
                />
              </Field>
              <Field
                label="Provenance note (required)"
                htmlFor="f-note"
                hint="Where does this projection come from — method, model or citation?"
                error={submitted && !form.note.trim() ? "Provenance note is required" : undefined}
              >
                <TextArea
                  id="f-note"
                  rows={2}
                  value={form.note}
                  onChange={(e) => set("note")(e.target.value)}
                  placeholder="e.g. national met-service seasonal outlook, 5% below-normal band"
                />
              </Field>
            </div>
            <div className="mt-4 flex items-center gap-3">
              <Button
                variant="primary"
                onClick={handleSubmit}
                disabled={!canSubmit || create.isPending}
                loading={create.isPending}
              >
                <CloudRain size={15} className="mr-1.5" />
                Record manual projection
              </Button>
              {create.isError ? (
                <span className="text-xs text-danger-dark">
                  {create.error instanceof Error ? create.error.message : "Failed to record."}
                </span>
              ) : null}
            </div>
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <CardHeader
          title="Forecast values (model + manual)"
          description={
            forecasts.data
              ? `${forecasts.data.total} value(s). Source indicates model-generated vs manual.`
              : undefined
          }
        />
        <CardBody>
          {forecasts.isLoading ? (
            <LoadingRows rows={4} />
          ) : forecasts.isError ? (
            <ErrorState error={forecasts.error} />
          ) : !forecasts.data || forecasts.data.items.length === 0 ? (
            <EmptyState
              title="No forecast values yet"
              description="Model-generated values appear after successful forecast runs; manual projections can be recorded above."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Indicator</th>
                    <th>Study area</th>
                    <th>Target date</th>
                    <th>Value / interval</th>
                    <th>Provenance / model</th>
                    <th>Recorded</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasts.data.items.map((f) => (
                    <tr key={f.id}>
                      <td>
                        <Badge
                          className={
                            f.source === "model"
                              ? "bg-water-50 text-water-800"
                              : "bg-canvas text-muted border border-border"
                          }
                        >
                          {f.source === "model" ? (
                            <span className="inline-flex items-center gap-1"><Gauge size={11} /> model</span>
                          ) : (
                            "manual"
                          )}
                        </Badge>
                      </td>
                      <td className="font-medium text-ink">{titleCase(f.indicator_key)}</td>
                      <td className="text-ink-soft">{f.study_area_name ?? f.study_area_id}</td>
                      <td className="text-ink-soft">{formatDate(f.target_date)}</td>
                      <td className="text-ink-soft tabular">
                        {formatNumber(f.value, { digits: 3 })} {f.unit}
                        {f.lower != null && f.upper != null ? (
                          <div className="text-xs text-muted">
                            {formatNumber(f.lower, { digits: 3 })}–{formatNumber(f.upper, { digits: 3 })} ({f.lead_time_days}d)
                          </div>
                        ) : null}
                      </td>
                      <td className="max-w-xs text-xs text-muted">
                        <p className="line-clamp-2" title={f.note}>
                          {f.source === "model" && (f.model_algorithm || f.model_name)
                            ? `${f.model_algorithm ?? "model"}${f.model_name ? ` · ${f.model_name}` : ""}`
                            : f.note}
                          {f.created_by_email ? ` — ${f.created_by_email}` : ""}
                        </p>
                      </td>
                      <td className="text-xs text-muted">
                        {formatDate(f.issued_at ?? f.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
