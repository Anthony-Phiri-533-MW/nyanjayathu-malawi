import { useState } from "react";
import { CloudRain } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextArea, TextInput } from "@/components/ui/Field";
import { ErrorState, EmptyState, LoadingRows } from "@/components/ui/States";
import { PageHeader, ProvisionalNote } from "@/components/PageHeader";
import {
  useCreateForecast,
  useForecasts,
  useIndicatorDefinitions,
  useStudyAreas,
} from "@/lib/hooks";
import { formatDate } from "@/lib/format";
import { useAuth } from "@/auth/AuthContext";

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

export function ForecastsPage() {
  const { can } = useAuth();
  const areas = useStudyAreas();
  const definitions = useIndicatorDefinitions();
  const forecasts = useForecasts({ size: 100 });
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

  const canWrite = can("disaster.evaluate.run");
  const set = (key: keyof typeof form) => (value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  const definitionUnit = (key: string): string => {
    const def = definitions.data?.find((d) => d.key === key);
    return def?.unit ?? "";
  };

  const optionForKey = (key: string): string => {
    // unit defaults from the indicator definition when the field is untouched
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
    canWrite &&
    form.indicator_key &&
    form.study_area_id &&
    form.target_date &&
    form.value &&
    form.note.trim();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Forecast values"
        description="Projected indicator values entered by authorised users. The disaster evaluation compares these against thresholds exactly like computed results — each alert records which source it used."
      />

      <ProvisionalNote>
        The platform does not generate forecasts itself. Values recorded here are user-supplied
        projections, so the provenance note is mandatory — state the source or method.
      </ProvisionalNote>

      {canWrite ? (
        <Card>
          <CardHeader title="Record a forecast value" />
          <CardBody>
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
                Record forecast
              </Button>
              <span className="text-xs text-muted">
                Requires the <span className="font-medium">disaster.evaluate.run</span> permission.
              </span>
            </div>
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <CardHeader
          title="Recorded forecasts"
          description={
            forecasts.data
              ? `${forecasts.data.total} value(s) recorded.`
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
              title="No forecast values recorded"
              description="Values recorded here participate in the next threshold evaluation."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Indicator</th>
                    <th>Study area</th>
                    <th>Target date</th>
                    <th>Value</th>
                    <th>Provenance</th>
                    <th>Recorded</th>
                  </tr>
                </thead>
                <tbody>
                  {forecasts.data.items.map((f) => (
                    <tr key={f.id}>
                      <td className="font-medium text-ink">{f.indicator_key}</td>
                      <td className="text-ink-soft">{f.study_area_name ?? f.study_area_id}</td>
                      <td className="text-ink-soft">{formatDate(f.target_date)}</td>
                      <td className="text-ink-soft">
                        {f.value} {f.unit}
                      </td>
                      <td className="max-w-xs text-xs text-muted">
                        <p className="line-clamp-2" title={f.note}>
                          {f.note}
                          {f.created_by_email ? ` — ${f.created_by_email}` : ""}
                        </p>
                      </td>
                      <td className="text-xs text-muted">{formatDate(f.created_at)}</td>
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
