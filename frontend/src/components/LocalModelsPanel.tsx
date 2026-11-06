import { useState } from "react";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextInput } from "@/components/ui/Field";
import { ErrorState, LoadingRows } from "@/components/ui/States";
import { useLocalModels, usePredictLocalModel } from "@/lib/hooks";
import { formatNumber } from "@/lib/format";

function localDateString() {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function seasonalFeatures(dateValue: string): Record<string, number> {
  if (!dateValue) return { sin_day: Number.NaN, cos_day: Number.NaN };
  const date = new Date(`${dateValue}T00:00:00Z`);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 0));
  const dayOfYear = Math.floor((date.getTime() - yearStart.getTime()) / 86_400_000);
  const angle = (2 * Math.PI * dayOfYear) / 365;
  return { sin_day: Math.sin(angle), cos_day: Math.cos(angle) };
}

export function LocalModelsPanel({ canRun }: { canRun: boolean }) {
  const models = useLocalModels();
  const predict = usePredictLocalModel();
  const [selectedKey, setSelectedKey] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [predictionDate, setPredictionDate] = useState(localDateString);
  const [submitted, setSubmitted] = useState(false);
  const selected = models.data?.find((model) => model.key === selectedKey);
  const visibleFeatures =
    selected?.key === "water_extent"
      ? selected.features.filter((feature) => feature.key !== "sin_day" && feature.key !== "cos_day")
      : selected?.features ?? [];
  const modelFeatures =
    selected?.key === "water_extent"
      ? {
          ...values,
          ...seasonalFeatures(predictionDate),
        }
      : values;
  const hasAllValues = Boolean(
    selected?.features.every(
      (feature) =>
        modelFeatures[feature.key]?.toString().trim() !== "" &&
        Number.isFinite(Number(modelFeatures[feature.key])),
    ),
  );

  const runPrediction = () => {
    setSubmitted(true);
    if (!selected || !hasAllValues || !canRun || !selected.ready) return;
    predict.mutate({
      modelKey: selected.key,
      features: Object.fromEntries(
        selected.features.map((feature) => [feature.key, Number(modelFeatures[feature.key])]),
      ),
    });
  };

  return (
    <Card>
      <CardHeader
        title="Local Lake Malawi models"
        description="Run the locally supplied regression models with explicit input values."
      />
      <CardBody className="space-y-4">
        <p className="text-xs text-muted">
          Predictions are estimates, not observations. Enter real values for the same prediction
          date; this tool does not invent missing inputs or save its result as an observation.
        </p>
        {models.isLoading ? (
          <LoadingRows rows={3} />
        ) : models.isError ? (
          <ErrorState error={models.error} onRetry={() => void models.refetch()} />
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {models.data?.map((model) => (
                <Badge
                  key={model.key}
                  className={model.ready ? "bg-success-light text-success-dark" : "bg-canvas text-muted"}
                >
                  {model.name}: {model.ready ? "ready" : "unavailable"}
                </Badge>
              ))}
            </div>
            <Field label="Model" htmlFor="local-model">
              <Select
                id="local-model"
                value={selectedKey}
                onChange={(event) => {
                  setSelectedKey(event.target.value);
                  setValues({});
                  setSubmitted(false);
                  predict.reset();
                }}
              >
                <option value="">Select a local model…</option>
                {(models.data ?? []).map((model) => (
                  <option key={model.key} value={model.key}>
                    {model.name}
                  </option>
                ))}
              </Select>
            </Field>
            {selected ? (
              <>
                <div className="rounded-md border border-border bg-canvas/60 p-3 text-xs text-muted">
                  <p className="font-medium text-ink">
                    Target: {selected.target} ({selected.unit})
                  </p>
                  {selected.key === "water_extent" ? (
                    <p className="mt-1">
                      This is an autoregressive forecast: past values of the target are used to
                      estimate its future value. That is different from measuring today&apos;s lake
                      extent. The supplied files do not establish whether the target is water level
                      or water area, or confirm its unit, so do not treat the output as km² without
                      checking the original training labels.
                    </p>
                  ) : null}
                  {selected.metrics_note}
                  {selected.metrics ? (
                    <span className="ml-1">
                      Reported metrics:{" "}
                      {Object.entries(selected.metrics)
                        .map(([key, value]) => `${key.toUpperCase()} ${formatNumber(value)}`)
                        .join(" · ")}.
                    </span>
                  ) : null}
                </div>
                {!selected.ready ? (
                  <p className="text-sm text-danger-dark" role="status">
                    {selected.unavailable_reason}
                  </p>
                ) : (
                  <>
                    {selected.key === "water_extent" ? (
                      <div className="space-y-2">
                        <Field label="Prediction date" htmlFor="water-prediction-date">
                          <TextInput
                            id="water-prediction-date"
                            type="date"
                            value={predictionDate}
                            aria-invalid={submitted && !predictionDate}
                            onChange={(event) => {
                              setPredictionDate(event.target.value);
                              predict.reset();
                            }}
                          />
                        </Field>
                        <p className="text-xs text-muted">
                          Day-of-year sine/cosine inputs are calculated from this date using the
                          model&apos;s 365-day feature formula.
                        </p>
                        {submitted && !predictionDate ? (
                          <p className="text-xs text-danger-dark">A prediction date is required.</p>
                        ) : null}
                      </div>
                    ) : null}
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      {visibleFeatures.map((feature) => (
                        <Field
                          key={feature.key}
                          label={`${feature.label} (${feature.unit})`}
                          htmlFor={`local-feature-${feature.key}`}
                          error={
                            submitted && !values[feature.key]?.trim()
                              ? "A value is required"
                              : submitted && !Number.isFinite(Number(values[feature.key]))
                                ? "Enter a finite number"
                                : undefined
                          }
                        >
                          <TextInput
                            id={`local-feature-${feature.key}`}
                            type="number"
                            step="any"
                            value={values[feature.key] ?? ""}
                            onChange={(event) =>
                              setValues((current) => ({
                                ...current,
                                [feature.key]: event.target.value,
                              }))
                            }
                          />
                        </Field>
                      ))}
                    </div>
                  </>
                )}
                {canRun ? null : (
                  <p className="text-xs text-muted">You need forecast-run permission to use a model.</p>
                )}
                {selected.ready ? (
                  <Button
                    variant="primary"
                    onClick={runPrediction}
                    disabled={!canRun || !hasAllValues || predict.isPending}
                    loading={predict.isPending}
                  >
                    Run prediction
                  </Button>
                ) : null}
              </>
            ) : null}
            {predict.isError ? (
              <p className="text-sm text-danger-dark" role="alert">
                Prediction failed: {predict.error.message}
              </p>
            ) : null}
            {predict.data ? (
              <div className="rounded-md border border-water-200 bg-water-50 p-4" role="status">
                <p className="text-xs font-medium uppercase tracking-wide text-water-800">
                  {predict.data.target} estimate
                </p>
                <p className="mt-1 text-2xl font-semibold tabular text-ink">
                  {formatNumber(predict.data.value, { unit: predict.data.unit })}
                </p>
                <p className="mt-1 text-xs text-muted">
                  {predict.data.model_name}. Not persisted as a forecast or observation.
                </p>
              </div>
            ) : null}
          </>
        )}
      </CardBody>
    </Card>
  );
}
