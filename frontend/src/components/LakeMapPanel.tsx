import { useEffect, useMemo, useRef, useState } from "react";
import {
  GeoJSON,
  LayersControl,
  MapContainer,
  TileLayer,
  useMap,
} from "react-leaflet";
import { circleMarker, geoJSON } from "leaflet";
import type { Feature, FeatureCollection, GeoJsonObject } from "geojson";
import "leaflet/dist/leaflet.css";
import { Pause, Play, RotateCw } from "lucide-react";
import { Link } from "react-router-dom";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { formatDate, formatNumber, titleCase } from "@/lib/format";
import { LAKE_MALAWI_FEATURE } from "@/data/lakeMalawi";
import type { PublicMapCollection, PublicWaterExtent } from "@/lib/types";

function layerPopup(text: string): HTMLElement {
  const popup = document.createElement("div");
  popup.textContent = text;
  return popup;
}

const LAKE_BOUNDS: [[number, number], [number, number]] = [
  [-14.5, 33.8],
  [-9.4, 35.4],
];

function FitStudyArea({ mapData }: { mapData: PublicMapCollection | undefined }) {
  const map = useMap();
  const hasFitted = useRef(false);

  useEffect(() => {
    if (!mapData || hasFitted.current) return;
    const area =
      mapData?.features.find((feature) => feature.properties.is_default) ??
      mapData?.features[0];
    if (area) {
      const bounds = geoJSON(area as unknown as GeoJsonObject).getBounds();
      if (bounds.isValid()) {
        map.setView(bounds.getCenter(), 7);
        hasFitted.current = true;
        return;
      }
    }
    map.fitBounds(LAKE_BOUNDS, { padding: [24, 24], maxZoom: 6 });
    hasFitted.current = true;
  }, [map, mapData]);

  return null;
}

export function LakeMapPanel({
  mapData,
  waterExtents,
  isLoading,
  isTimelineLoading,
  mapError,
  timelineError,
  onRetry,
}: {
  mapData: PublicMapCollection | undefined;
  waterExtents: PublicWaterExtent[];
  isLoading: boolean;
  isTimelineLoading: boolean;
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
  const hasPublishedLayers =
    (mapData?.features.length ?? 0) > 0 ||
    (mapData?.dataset_coverages.length ?? 0) > 0 ||
    (mapData?.indicator_observations?.length ?? 0) > 0 ||
    frames.length > 0;

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
  const indicatorLayers = useMemo(() => {
    const groups = new Map<string, { name: string; features: Feature[] }>();
    for (const observation of mapData?.indicator_observations ?? []) {
      const { indicator_key, indicator_name } = observation.properties;
      const group = groups.get(indicator_key) ?? { name: indicator_name, features: [] };
      group.features.push(observation as unknown as Feature);
      groups.set(indicator_key, group);
    }
    return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [mapData]);

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
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
              hasPublishedLayers
                ? "bg-success-light text-success-dark"
                : "bg-canvas text-muted"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                hasPublishedLayers ? "bg-success" : "bg-muted"
              }`}
            />
            {isLoading
              ? "Loading public layers…"
              : hasPublishedLayers
                ? "Published layers available"
                : "Lake outline only"}
          </span>
        }
      />
      <div className="h-[34rem] sm:h-[42rem]">
        <MapContainer
          center={[-12, 34.6]}
          zoom={5}
          zoomSnap={0.5}
          maxZoom={13}
          scrollWheelZoom
          className="h-full w-full"
        >
          <FitStudyArea mapData={mapData} />
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
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
                      fillOpacity: 0.08,
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
                      weight: 1,
                      fillColor: raw ? "#60a5fa" : "#eec25b",
                      fillOpacity: 0.15,
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
            {indicatorLayers.map(([key, layer], index) => {
              const color = [
                "#b45309",
                "#047857",
                "#7c3aed",
                "#be123c",
                "#0369a1",
                "#4d7c0f",
              ][index % 6];
              const collection: FeatureCollection = {
                type: "FeatureCollection",
                features: layer.features,
              };
              return (
                <LayersControl.Overlay
                  key={key}
                  checked={key === "water_extent"}
                  name={`${layer.name}${layer.features.length > 1 ? ` (${layer.features.length})` : ""}`}
                >
                  <GeoJSON
                    data={collection}
                    style={{
                      color,
                      weight: 2,
                      fillColor: color,
                      fillOpacity: 0.3,
                    }}
                    pointToLayer={(_feature, latlng) =>
                      circleMarker(latlng, {
                        radius: 8,
                        color,
                        fillColor: color,
                        fillOpacity: 0.85,
                        weight: 2,
                      })
                    }
                    onEachFeature={(feature, layerObject) => {
                      const properties = feature.properties ?? {};
                      const metric = formatNumber(Number(properties.value), {
                        unit: String(properties.unit ?? ""),
                      });
                      const period =
                        properties.observed_start === properties.observed_end
                          ? formatDate(String(properties.observed_start))
                          : `${formatDate(String(properties.observed_start))} – ${formatDate(String(properties.observed_end))}`;
                      layerObject.bindPopup(
                        layerPopup(
                          `${properties.indicator_name}: ${metric} · ${period} · ${properties.quality_flag}${properties.is_proxy ? " · proxy estimate" : ""} · ${properties.dataset_title}`,
                        ),
                      );
                    }}
                  />
                </LayersControl.Overlay>
              );
            })}
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
        {!isLoading && !mapError && indicatorLayers.length === 0 ? (
          <p className="rounded-md border border-border bg-white px-3 py-2 text-xs text-muted">
            No published indicator observations are available to draw yet. Compute an indicator
            from a dataset with spatial coverage, then publish that dataset to add its layer here.
          </p>
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
          ) : isTimelineLoading ? (
            <p className="mt-3 rounded-md bg-white px-3 py-2 text-xs text-muted" role="status">
              Loading published shoreline frames…
            </p>
          ) : timelineError ? (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-danger-light px-3 py-2 text-xs text-danger-dark" role="alert">
              <span>Published shoreline frames could not be loaded: {timelineError.message}</span>
              <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={onRetry}>
                <RotateCw size={13} /> Retry
              </button>
            </div>
          ) : (
            <div className="mt-3 rounded-md bg-white px-3 py-3 text-xs leading-relaxed text-muted">
              <p className="font-medium text-ink">No published shoreline frames yet.</p>
              <p className="mt-1">
                The map and lake outline are available; the time-lapse needs real water-extent
                polygons. A staff member must:
              </p>
              <ol className="mt-1 list-inside list-decimal space-y-0.5">
                <li>Ingest dated Sentinel-2 or Landsat imagery covering the lake.</li>
                <li>Compute <code>water_extent</code> from imagery with suitable water-index bands.</li>
                <li>Publish each source dataset so its computed shoreline is public.</li>
              </ol>
              <p className="mt-2">
                Only computed polygons are shown; the lake outline is not used as a substitute
                for observations.
              </p>
              <Link to="/login" className="mt-2 inline-block text-water-700 underline underline-offset-2">
                Staff sign in
              </Link>
            </div>
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
            Indicator observation footprint / location
          </span>
          <span className="text-[11px]">
            Indicator colors show observation footprints and summary values, not per-pixel readings.
          </span>
          <span className="text-[11px]">
            Basemap tiles: Esri and its data providers. Lake outline: © OpenStreetMap contributors (ODbL).
          </span>
        </div>
      </CardBody>
    </Card>
  );
}
