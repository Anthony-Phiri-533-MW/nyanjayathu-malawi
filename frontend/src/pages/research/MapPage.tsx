import { useMemo, useState } from "react";
import { MapContainer, TileLayer, GeoJSON, LayersControl } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { Globe } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Badge, Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Field, Select, TextInput } from "@/components/ui/Field";
import { ErrorState, LoadingRows } from "@/components/ui/States";
import type { Feature, FeatureCollection, GeoJsonObject } from "geojson";
import { useAuth } from "@/auth/AuthContext";
import { useDatasets, useStudyAreas, useRequestIngestion, useDataSources, usePublish } from "@/lib/hooks";
import { ApiError } from "@/lib/api";
import { titleCase } from "@/lib/format";

const LAKE_MALAWI_CENTER: [number, number] = [-12.5, 34.6];

export function MapPage() {
  const [page] = useState(1);
  const studyAreas = useStudyAreas();
  const datasets = useDatasets({ page, size: 100 });
  const showStudyAreas = true;
  const { can: hasPermission } = useAuth();
  const canPublish = hasPermission("public.publish");
  const publish = usePublish("study-areas", ["study-areas"]);

  const defaultArea = studyAreas.data?.find((a) => a.is_default) ?? studyAreas.data?.[0];
  const center: [number, number] = defaultArea
    ? [(defaultArea.miny + defaultArea.maxy) / 2, (defaultArea.minx + defaultArea.maxx) / 2]
    : LAKE_MALAWI_CENTER;

  const coverageFeatures = useMemo<Feature[]>(
    () =>
      (datasets.data?.items ?? [])
        .filter((d) => d.coverage_geojson)
        .map((d) => ({
          type: "Feature" as const,
          properties: { title: d.title, isRaw: d.is_raw, quality: d.quality_flag },
          geometry: d.coverage_geojson as unknown as Feature["geometry"],
        })),
    [datasets.data],
  );

  const coverageCollection: FeatureCollection = {
    type: "FeatureCollection",
    features: coverageFeatures,
  };

  return (
    <div>
      <PageHeader
        title="Map"
        description="Study-area boundaries and the recorded spatial coverage of stored datasets. Coverage shows where data is stored — it is not itself a measurement of water extent."
      />

      <div className="grid gap-5 lg:grid-cols-4">
        <Card className="lg:col-span-3">
          <div className="h-[32rem] overflow-hidden rounded-card">
            <MapContainer center={center} zoom={7} scrollWheelZoom className="h-full w-full">
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <LayersControl position="topright">
                {showStudyAreas && studyAreas.data
                  ? studyAreas.data.map((area) => (
                      <LayersControl.Overlay key={area.id} checked name={`Study area: ${area.name}`}>
                        <GeoJSON
                          data={area.boundary_geojson as unknown as GeoJsonObject}
                          style={{
                            color: "#17497f",
                            weight: 2,
                            fillColor: "#3b82f6",
                            fillOpacity: 0.08,
                          }}
                        />
                      </LayersControl.Overlay>
                    ))
                  : null}
                {coverageFeatures.length > 0 ? (
                  <LayersControl.Overlay checked name="Dataset coverage">
                    <GeoJSON
                      data={coverageCollection}
                      style={(feature) => {
                        const isRaw = feature?.properties?.isRaw as boolean | undefined;
                        return {
                          color: isRaw ? "#1d5fa8" : "#c8891a",
                          weight: 1,
                          fillColor: isRaw ? "#60a5fa" : "#eec25b",
                          fillOpacity: 0.15,
                        };
                      }}
                      onEachFeature={(feature, layer) => {
                        const p = feature.properties ?? {};
                        layer.bindPopup(
                          `<strong>${p.title ?? "Dataset"}</strong><br/>` +
                            `${p.isRaw ? "Observed" : "Derived"} · quality: ${p.quality ?? "—"}`,
                        );
                      }}
                    />
                  </LayersControl.Overlay>
                ) : null}
              </LayersControl>
            </MapContainer>
          </div>
          <CardBody className="border-t border-border">
            <div className="flex flex-wrap items-center gap-4 text-xs text-muted">
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-3 w-3 rounded-sm border border-water-600 bg-water-300/40" />
                Observed retrieval
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-3 w-3 rounded-sm border border-signal-500 bg-signal-200/50" />
                Derived product
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block h-3 w-3 rounded-sm border-2 border-water-700" />
                Study-area boundary
              </span>
              {coverageFeatures.length === 0 ? (
                <span>No dataset footprints recorded yet.</span>
              ) : null}
            </div>
          </CardBody>
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Study areas" description={`${studyAreas.data?.length ?? 0} defined`} />
            {studyAreas.isLoading ? (
              <LoadingRows rows={2} />
            ) : studyAreas.isError ? (
              <ErrorState error={studyAreas.error} onRetry={() => studyAreas.refetch()} />
            ) : (
              <ul className="divide-y divide-border">
                {(studyAreas.data ?? []).map((area) => (
                  <li key={area.id} className="px-5 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium text-ink">{area.name}</p>
                      <div className="flex items-center gap-1">
                        {area.is_default ? (
                          <Badge className="bg-water-50 text-water-700">Default</Badge>
                        ) : null}
                        {canPublish ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            loading={publish.isPending}
                            onClick={() => publish.mutate({ id: area.id, is_public: !area.is_public })}
                          >
                            <Globe size={13} />
                            {area.is_public ? "Public" : "Publish"}
                          </Button>
                        ) : area.is_public ? (
                          <Badge className="bg-success-light text-success-dark">Public</Badge>
                        ) : null}
                      </div>
                    </div>
                    <p className="mt-0.5 text-xs text-muted">
                      {area.miny.toFixed(3)}°–{area.maxy.toFixed(3)}°S,{" "}
                      {area.minx.toFixed(3)}°–{area.maxx.toFixed(3)}°E
                    </p>
                    {area.description ? (
                      <p className="mt-1 text-xs text-muted">{area.description}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <IngestionCard />
        </div>
      </div>
    </div>
  );
}

/**
 * Ingestion request form. The shape of the request mirrors the API; the
 * backend revalidates every field (including that the selected source is
 * enabled and the dates are within the source's declared span).
 */
function IngestionCard() {
  const sources = useDataSources({ page: 1, size: 100 });
  const studyAreas = useStudyAreas();
  const request = useRequestIngestion();

  const [sourceId, setSourceId] = useState("");
  const [areaId, setAreaId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [banner, setBanner] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  const enabledSources = (sources.data?.items ?? []).filter((s) => s.is_enabled);

  return (
    <Card>
      <CardHeader
        title="Request ingestion"
        description="Retrieve data from a configured source. The job is queued and runs in the background."
      />
      <form
        className="space-y-4 px-5 py-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setBanner(null);
          try {
            const job = await request.mutateAsync({
              data_source_id: Number(sourceId),
              study_area_id: Number(areaId),
              start_date: startDate,
              end_date: endDate,
            });
            setBanner({ tone: "ok", text: `Queued ingestion job #${job.job_id}.` });
          } catch (error) {
            setBanner({
              tone: "error",
              text: error instanceof ApiError ? error.message : "Could not queue the job.",
            });
          }
        }}
      >
        <Field label="Data source" htmlFor="ing-source" required>
          <Select
            id="ing-source"
            value={sourceId}
            onChange={(e) => setSourceId(e.target.value)}
            required
          >
            <option value="">Select a source…</option>
            {enabledSources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} ({titleCase(s.category)})
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Study area" htmlFor="ing-area" required>
          <Select id="ing-area" value={areaId} onChange={(e) => setAreaId(e.target.value)} required>
            <option value="">Select an area…</option>
            {(studyAreas.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Start date" htmlFor="ing-start" required>
            <TextInput
              id="ing-start"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              required
            />
          </Field>
          <Field label="End date" htmlFor="ing-end" required>
            <TextInput
              id="ing-end"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              required
            />
          </Field>
        </div>

        {enabledSources.length === 0 ? (
          <p className="text-xs text-muted">
            No enabled data sources. Configure one under Administration → Data sources.
          </p>
        ) : null}

        {banner ? (
          <p
            className={
              banner.tone === "ok"
                ? "rounded-md border border-success/30 bg-success-light px-3 py-2 text-xs text-success-dark"
                : "rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-xs text-danger-dark"
            }
          >
            {banner.text}
          </p>
        ) : null}

        <Button
          type="submit"
          className="w-full"
          loading={request.isPending}
          disabled={!sourceId || !areaId || !startDate || !endDate}
        >
          Queue ingestion
        </Button>
      </form>
    </Card>
  );
}
