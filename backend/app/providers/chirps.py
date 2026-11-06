"""CHIRPS v2.0 daily rainfall adapter (Climate Hazards Center, UCSB).

Verified live (2026-10-21): the daily 0.05 deg GeoTIFF bundle for a given day
is published as a gzip-compressed GeoTIFF at

    {base}/global_daily/tifs/p05/{YYYY}/chirps-v2.0.{Y}.{M}.{D}.tif.gz

Discovery is deterministic from the date range (one item per day); retrieval
downloads the bundle, checksums it, decompresses, windows it to the study
area and stores a small GeoTIFF.  Values are mm/day and are not rescaled.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from app.core.config import settings
from app.providers.base import (
    DiscoveredItem,
    FetchedArtifact,
    IngestParams,
    ProgressFn,
    ProviderAdapter,
    ProviderError,
    TestResult,
    _noop_progress,
)
from app.providers.raster import AssetRule, download_file, gunzip, head_status

log = logging.getLogger("lakewatch.providers.chirps")

CHIRPS_FIRST_DAY = date(1981, 1, 1)
PRECIP_RULE = AssetRule(scale=1.0, offset=0.0, unit="mm/day", label="Daily precipitation", canonical="precipitation")


class ChirpsAdapter(ProviderAdapter):
    key = "chirps"
    label = "CHIRPS v2.0 daily rainfall"
    category = "satellite_rainfall"
    product_type = "CHIRPS v2.0 daily precipitation (0.05 deg, mm/day)"
    description = (
        "Climate Hazards Center CHIRPS v2.0 daily precipitation (0.05 deg, "
        "1981-present), public GeoTIFF bundles. Each day is downloaded, "
        "checksummed, decompressed and windowed to the study area; values are "
        "mm/day as published (no rescaling)."
    )
    adapter_status = "tested"
    verification_note = "Daily GeoTIFF bundle URL verified live (HTTP 200, ~3.2 MB) on 2026-10-21."
    capabilities = {
        "spatial_filter": True,
        "temporal_filter": True,
        "raster": True,
        "precipitation": True,
        "time_series": True,
        "stac_search": False,
    }
    default_variables = [
        {"key": "precipitation", "label": "Daily precipitation", "unit": "mm/day"}
    ]

    def _base(self) -> str:
        return str(self.config.get("base_url") or settings.chirps_base_url).rstrip("/")

    def daily_url(self, day: date) -> str:
        return (
            f"{self._base()}/global_daily/tifs/p05/{day:%Y}/"
            f"chirps-v2.0.{day:%Y}.{day:%m}.{day:%d}.tif.gz"
        )

    # -- ProviderAdapter API ----------------------------------------------
    def test_connection(self) -> TestResult:
        import time

        started = time.perf_counter()
        # a day known to exist (CHIRPS starts 1981-01-01) keeps the test deterministic
        url = self.daily_url(date(2020, 1, 1))
        status = head_status(self.client, url)
        latency = int((time.perf_counter() - started) * 1000)
        if status == 200:
            return TestResult(ok=True, message="CHIRPS daily GeoTIFF is reachable", latency_ms=latency, details={"url": url})
        if status is None:
            return TestResult(ok=False, message="CHIRPS host unreachable (network error)", latency_ms=latency, details={"url": url})
        return TestResult(ok=False, message=f"CHIRPS returned HTTP {status}", latency_ms=latency, details={"url": url})

    def discover(self, params: IngestParams) -> list[DiscoveredItem]:
        start = max(params.start_date, CHIRPS_FIRST_DAY)
        if start > params.end_date:
            raise ProviderError(
                f"requested range ends before CHIRPS availability ({CHIRPS_FIRST_DAY.isoformat()})"
            )
        cap = max(1, int(params.max_items or 60))
        items: list[DiscoveredItem] = []
        day = start
        while day <= params.end_date and len(items) < cap:
            items.append(
                DiscoveredItem(
                    asset_id=f"chirps-v2.0-{day.isoformat()}",
                    title=f"CHIRPS daily precipitation {day.isoformat()}",
                    start_date=day,
                    end_date=day,
                    bbox=params.bbox,
                    media_type="application/gzip",
                    metadata={
                        "url": self.daily_url(day),
                        "product": "CHIRPS-2.0 daily p05",
                        "resolution_degrees": 0.05,
                    },
                    assets={"precipitation": self.daily_url(day)},
                )
            )
            day += timedelta(days=1)
        if day <= params.end_date:
            raise ProviderError(
                f"CHIRPS date range requires more than the configured item limit ({cap}); "
                "narrow the date range or increase the source limit"
            )
        return items

    def fetch(self, params: IngestParams, item: DiscoveredItem, progress: ProgressFn = _noop_progress) -> FetchedArtifact:
        from app.services.storage import file_checksum, new_workspace, relative

        url = item.metadata.get("url") or item.assets.get("precipitation")
        if not url:
            raise ProviderError(f"item '{item.asset_id}' has no precipitation URL")
        workspace = params.dest_dir or new_workspace("raw")
        workspace.mkdir(parents=True, exist_ok=True)
        slug = str(item.start_date or item.asset_id)
        gz_path = workspace / f"chirps_{slug}.tif.gz"
        tif_path = workspace / f"chirps_{slug}.tif"
        out_path = workspace / f"chirps_{slug}_precip.tif"

        size, _ = download_file(self.client, url, gz_path)
        source_checksum = file_checksum(gz_path)
        progress(0.5, "downloaded CHIRPS bundle")
        gunzip(gz_path, tif_path)

        from app.providers.raster import fetch_raster_band

        lat_ref = (params.bbox[1] + params.bbox[3]) / 2.0 if params.bbox else None
        meta = fetch_raster_band(
            str(tif_path),
            out_path,
            native_name="precipitation",
            bbox=params.bbox,
            rule=PRECIP_RULE,
            max_dim=int((params.extra or {}).get("max_dim") or 2048),
            lat_ref=lat_ref,
            extra_tags={"source_item": item.asset_id, "source_url": url},
        )
        # keep only the windowed product; the global tile is not retained
        for tmp in (gz_path, tif_path):
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:  # pragma: no cover - best effort cleanup
                pass
        progress(1.0, "stored windowed precipitation")

        return FetchedArtifact(
            item=item,
            path=relative(workspace),
            size_bytes=out_path.stat().st_size,
            checksum=file_checksum(out_path),
            variables=["precipitation"],
            metadata={
                "format": "geotiff",
                "granules": [
                    {
                        "id": item.asset_id,
                        "date": item.start_date.isoformat() if item.start_date else None,
                        "path": relative(out_path),
                        "band": "precipitation",
                    }
                ],
                "bands": {
                    "precipitation": {
                        **meta,
                        "unit": PRECIP_RULE.unit,
                        "label": PRECIP_RULE.label,
                        "scale": 1.0,
                        "offset": 0.0,
                    }
                },
                "source_url": url,
                "source_bundle_bytes": size,
                "source_checksum_sha256": source_checksum,
                "scene_bbox": list(item.bbox) if item.bbox else None,
                "max_dim": int((params.extra or {}).get("max_dim") or 2048),
            },
        )
