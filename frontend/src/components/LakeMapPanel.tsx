import { useEffect, useMemo, useState } from "react";
import {
  GeoJSON,
  LayersControl,
  MapContainer,
  TileLayer,
} from "react-leaflet";
import type { Feature, FeatureCollection, GeoJsonObject } from "geojson";
import "leaflet/dist/leaflet.css";
import { Pause, Play, RotateCw } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { formatDate, formatNumber, titleCase } from "@/lib/format";
import { LAKE_MALAWI_FEATURE } from "@/data/lakeMalawi";
import type { PublicMapCollection, PublicWaterExtent } from "@/lib/types";

function layerPopup(text: string): HTMLElement {
  const popup = document.createElement("div");
  popup.textContent = text;
  return popup;
}

/** Keep the map focused on Malawi and the lake's full shoreline. */
const MALAWI_BOUNDS: [[number, number], [number, number]] = [
  [-17.2, 32.6], // south-west
  [-9.3, 35.9], // north-east
];

export function LakeMapPanel({
  mapData,
  waterExtents,
  isLoading,
  mapError,
  timelineError,
  onRetry,
}: {
  mapData: PublicMapCollection | undefined;
  waterExtents: PublicWaterExtent[];
  isLoading: boolean;
  mapError?: Error | null;
  timelineError?: Error | null;
  onRetry: () => void;
}) {
  const [frameIndex, setFrameIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  const frames = useMemo(
    () =>
      [...waterExtents].sort(
        (a, b) =>
          a.observed_start.localeCompare(b.observed_start) ||
          a.id - b.id,
      ),
    [waterExtents],
  );
  const selectedFrame = frames[frameIndex];

  const areas: FeatureCollection = useMemo(
    () => ({
      type: "FeatureCollection",
      features: (mapData?.features ?? []) as unknown as Feature[],
    }),
    [mapData],
  );
  const coverages: FeatureCollection = useMemo(
    () => ({
      type: "FeatureCollection",
      features: (mapData?.dataset_coverages ?? []) as unknown as Feature[],
    }),
    [mapData],
  );

  useEffect(() => {
    if (frameIndex >= frames.length && frames.length > 0) {
      setFrameIndex(frames.length - 1);
    }
    if (frames.length < 2) setIsPlaying(false);
  }, [frameIndex, frames.length]);

  useEffect(() => {
    if (!isPlaying || frames.length < 2) return;
    const timer = window.setInterval(
      () => setFrameIndex((current) => (current + 1) % frames.length),
      1200,
    );
    return () => window.clearInterval(timer);
  }, [frames.length, isPlaying]);

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Lake Malawi"
        description="Published observations appear automatically. Toggle layers to compare public study areas, data coverage and mapped water extents."
        actions={
          <span className="inline-flex items-center gap-1.5 rounded-full bg-success-light px-2.5 py-1 text-xs font-medium text-success-dark">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            Live published data
          </span>
        }
      />
      <div className="h-[34rem] sm:h-[42rem]">
        <MapContainer
          center={[-13.25, 34.25]}
          zoom={5}
          minZoom={4}
          maxZoom={13}
          maxBounds={MALAWI_BOUNDS}
          maxBoundsViscosity={1.0}
          scrollWheelZoom
          className="h-full w-full"
        >
          <TileLayer
            attribution='Tiles &copy; <a href="https://www.esri.com/">Esri</a> — Sources: Esri, HERE, Garmin, FAO, NOAA, USGS, EPA, NPS, and the GIS User Community'
            url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
          />
          <LayersControl position="topright">
            <LayersControl.Overlay checked name="Lake Malawi / Nyasa shoreline">
              <GeoJSON
                data={LAKE_MALAWI_FEATURE}
                style={{
                  color: "#0f5f9e",
                  weight: 2,
                  fillColor: "#38bdf8",
                  fillOpacity: 0.45,
                }}
                onEachFeature={(_feature, layer) => {
                  layer.bindTooltip("Lake Malawi / Nyasa", { sticky: true });
                }}
              />
            </LayersControl.Overlay>
            {areas.features.length > 0 ? (
              <LayersControl.Overlay checked name="Published study areas">
                <GeoJSON
                  data={areas}
                  style={(feature) => {
                    const critical =
                      feature?.properties?.highest_active_severity === "critical";
                    return {
                      color: critical ? "#b3261e" : "#17497f",
                      weight: 2,
                      fillColor: critical ? "#ef7670" : "#60a5fa",
                      fillOpacity: 0.12,
                    };
                  }}
                  onEachFeature={(feature, layer) => {
                    const properties = feature.properties ?? {};
                    layer.bindPopup(
                      layerPopup(
                        `${properties.name ?? "Published study area"} · ${properties.public_dataset_count ?? 0} dataset(s) · ${properties.active_public_alerts ?? 0} active alert(s)`,
                      ),
                    );
                  }}
                />
              </LayersControl.Overlay>
            ) : null}
            {coverages.features.length > 0 ? (
              <LayersControl.Overlay checked name="Published dataset coverage">
                <GeoJSON
                  data={coverages}
                  style={(feature) => {
                    const raw = feature?.properties?.is_raw as boolean | undefined;
                    return {
                      color: raw ? "#1d5fa8" : "#c8891a",
                      weight: 1.5,
                      fillColor: raw ? "#60a5fa" : "#eec25b",
                      fillOpacity: 0.18,
                    };
                  }}
                  onEachFeature={(feature, layer) => {
                    const properties = feature.properties ?? {};
                    layer.bindPopup(
                      layerPopup(
                        `${properties.title ?? "Published dataset"} · ${properties.start_date ?? "undated"} to ${properties.end_date ?? "undated"}`,
                      ),
                    );
                  }}
                />
              </LayersControl.Overlay>
            ) : null}
            {selectedFrame ? (
              <LayersControl.Overlay checked name="Mapped water extent">
                <GeoJSON
                  key={selectedFrame.id}
                  data={selectedFrame.spatial_extent_geojson as unknown as GeoJsonObject}
                  style={{
                    color: "#0e7490",
                    weight: 2,
                    fillColor: "#22d3ee",
                    fillOpacity: 0.5,
                  }}
                  onEachFeature={(_feature, layer) => {
                    layer.bindPopup(
                      layerPopup(
                        `${selectedFrame.dataset_title} · ${formatDate(selectedFrame.observed_start)} · ${formatNumber(selectedFrame.value, { unit: selectedFrame.unit })}`,
                      ),
                    );
                  }}
                />
              </LayersControl.Overlay>
            ) : null}
          </LayersControl>
        </MapContainer>
      </div>
      <CardBody className="space-y-4 border-t border-border">
        {isLoading ? (
          <p className="text-xs text-muted">Loading the latest published map layers…</p>
        ) : null}
        {mapError ? (
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-danger-dark" role="alert">
            <span>Published map layers could not be refreshed: {mapError.message}</span>
            <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={onRetry}>
              <RotateCw size={13} /> Retry
            </button>
          </div>
        ) : null}

        <div className="rounded-lg border border-border bg-canvas/70 p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-ink">Water extent time-lapse</p>
              <p className="text-xs text-muted">
                Satellite-derived shoreline frames, not water-level measurements.
              </p>
            </div>
            {selectedFrame ? (
              <div className="text-right">
                <p className="text-sm font-semibold tabular text-ink">
                  {formatNumber(selectedFrame.value, { unit: selectedFrame.unit })}
                </p>
                <p className="text-xs text-muted">{formatDate(selectedFrame.observed_start)}</p>
              </div>
            ) : null}
          </div>
          {frames.length > 0 ? (
            <div className="mt-3 flex items-center gap-3">
              <button
                type="button"
                className="btn-secondary h-9 w-9 shrink-0 px-0"
                aria-label={isPlaying ? "Pause time-lapse" : "Play time-lapse"}
                disabled={frames.length < 2}
                onClick={() => setIsPlaying((playing) => !playing)}
              >
                {isPlaying ? <Pause size={15} /> : <Play size={15} />}
              </button>
              <input
                className="w-full accent-water-700"
                type="range"
                min={0}
                max={frames.length - 1}
                value={frameIndex}
                aria-label="Select water extent observation"
                onChange={(event) => {
                  setIsPlaying(false);
                  setFrameIndex(Number(event.target.value));
                }}
              />
              <span className="shrink-0 text-xs tabular text-muted">
                {frameIndex + 1}/{frames.length}
              </span>
            </div>
          ) : (
            <p className="mt-3 rounded-md bg-white px-3 py-2 text-xs leading-relaxed text-muted">
              {timelineError
                ? `Published shoreline observations could not be loaded: ${timelineError.message}`
                : "No published shoreline polygons yet. The time-lapse will appear automatically after water-extent polygons are computed from dated imagery and their source datasets are published."}
            </p>
          )}
          {selectedFrame && selectedFrame.quality_flag !== "VALID" ? (
            <p className="mt-2 text-xs text-warning-dark">
              Frame quality: {titleCase(selectedFrame.quality_flag)}. Treat this mapped result as indicative.
            </p>
          ) : null}
          {selectedFrame ? (
            <p className="mt-1 text-xs text-muted">
              The water-mask threshold is provisional and requires local validation.
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-4 text-xs text-muted">
          <span className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-sm border border-teal-700 bg-teal-400/60" />
            Lake outline
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-sm border border-water-600 bg-water-300/40" />
            Published study area / observation
          </span>
          <span className="text-[11px]">Map tiles and lake outline: © OpenStreetMap contributors (ODbL)</span>
        </div>
      </CardBody>
    </Card>
  );
}
