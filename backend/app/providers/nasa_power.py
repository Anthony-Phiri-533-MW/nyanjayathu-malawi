"""NASA POWER daily point meteorology adapter.

Verified live (2026-10-21): ``GET {base}/temporal/daily/point`` with
``community=AG`` returns a daily series for a coordinate; the response carries
parameter units and a ``fill_value`` (-999.0) in its header, which this
adapter records and applies (filled values become blanks, never zero).

POWER is a **point** product: it is sampled at the representative coordinate of
the study area (bbox centre) and stored as a tidy daily CSV.  The coordinate is
recorded in provenance so results are never mistaken for spatially resolved
fields.
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

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

log = logging.getLogger("lakewatch.providers.power")

DEFAULT_PARAMETERS = ["T2M", "PRECTOTCORR", "WS2M", "ALLSKY_SFC_SW_DWN"]
MAX_CHUNK_DAYS = 365
DEFAULT_FILL = -999.0


class NasaPowerAdapter(ProviderAdapter):
    key = "nasa_power"
    label = "NASA POWER daily meteorology (point)"
    category = "satellite_temperature"
    product_type = "NASA POWER daily point meteorology (temperature, precipitation, wind, solar)"
    description = (
        "NASA POWER daily point API (MERRA-2 based) sampled at the study-area "
        "representative coordinate. Daily values in the units reported by the "
        "API; missing values (fill value -999) are stored as blanks. This is a "
        "point source - not a spatially resolved field or a lake-surface "
        "temperature."
    )
    adapter_status = "tested"
    verification_note = "Daily point API verified live (HTTP 200) on 2026-10-21."
    capabilities = {
        "spatial_filter": False,
        "temporal_filter": True,
        "point_series": True,
        "temperature": True,
        "precipitation": True,
        "raster": False,
        "stac_search": False,
    }
    default_variables = [
        {"key": "T2M", "label": "2 m air temperature", "unit": "C"},
        {"key": "PRECTOTCORR", "label": "Corrected precipitation", "unit": "mm/day"},
        {"key": "WS2M", "label": "2 m wind speed", "unit": "m/s"},
        {"key": "ALLSKY_SFC_SW_DWN", "label": "All-sky surface shortwave radiation", "unit": "kWh/m2/day"},
    ]

    def _base(self) -> str:
        return str(self.config.get("base_url") or settings.nasa_power_base_url).rstrip("/")

    def _point(self, params: IngestParams) -> tuple[float, float]:
        cfg = self.config.get("point") or {}
        lon = cfg.get("longitude")
        lat = cfg.get("latitude")
        if lon is not None and lat is not None:
            return float(lon), float(lat)
        minx, miny, maxx, maxy = params.bbox
        return round((minx + maxx) / 2.0, 4), round((miny + maxy) / 2.0, 4)

    def _parameters(self, params: IngestParams) -> list[str]:
        chosen = [str(v) for v in (params.variables or []) if v]
        return chosen or list(self.config.get("parameters") or DEFAULT_PARAMETERS)

    def _query(self, *, lon: float, lat: float, start: date, end: date, parameters: list[str]) -> dict[str, str]:
        return {
            "parameters": ",".join(parameters),
            "community": "AG",
            "longitude": f"{lon}",
            "latitude": f"{lat}",
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "format": "JSON",
        }

    # -- ProviderAdapter API ----------------------------------------------
    def test_connection(self) -> TestResult:
        import time

        started = time.perf_counter()
        url = f"{self._base()}/temporal/daily/point"
        params = self._query(lon=34.9, lat=-12.1, start=date(2024, 1, 1), end=date(2024, 1, 5), parameters=["T2M"])
        try:
            resp = self.client.get(url, params=params)
        except Exception as exc:
            return TestResult(ok=False, message=f"NASA POWER unreachable: {exc}")
        latency = int((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            return TestResult(ok=False, message=f"NASA POWER returned HTTP {resp.status_code}", latency_ms=latency)
        try:
            payload = resp.json()
        except ValueError:
            return TestResult(ok=False, message="NASA POWER returned non-JSON body", latency_ms=latency)
        has_series = bool((payload.get("properties") or {}).get("parameter"))
        return TestResult(
            ok=has_series,
            message="NASA POWER daily point API responded with a parameter series"
            if has_series
            else "NASA POWER response did not contain a parameter series",
            latency_ms=latency,
            details={"api_version": (payload.get("header") or {}).get("api", {}).get("version")},
        )

    def discover(self, params: IngestParams) -> list[DiscoveredItem]:
        lon, lat = self._point(params)
        params_list = self._parameters(params)
        cap = max(1, int(params.max_items or 60))
        items: list[DiscoveredItem] = []
        chunk_start = params.start_date
        while chunk_start <= params.end_date and len(items) < cap:
            chunk_end = min(chunk_start + timedelta(days=MAX_CHUNK_DAYS - 1), params.end_date)
            items.append(
                DiscoveredItem(
                    asset_id=f"power_{lat}_{lon}_{chunk_start.isoformat()}_{chunk_end.isoformat()}",
                    title=f"NASA POWER daily series {chunk_start.isoformat()} - {chunk_end.isoformat()}",
                    start_date=chunk_start,
                    end_date=chunk_end,
                    bbox=params.bbox,
                    media_type="application/json",
                    metadata={
                        "sample_point": [lon, lat],
                        "parameters": params_list,
                        "community": "AG",
                    },
                    assets={},
                )
            )
            chunk_start = chunk_end + timedelta(days=1)
        return items

    def fetch(self, params: IngestParams, item: DiscoveredItem, progress: ProgressFn = _noop_progress) -> FetchedArtifact:
        from app.services.storage import file_checksum, new_workspace, relative

        lon, lat = item.metadata.get("sample_point") or self._point(params)
        parameters = list(item.metadata.get("parameters") or self._parameters(params))
        start = item.start_date
        end = item.end_date
        url = f"{self._base()}/temporal/daily/point"
        query = self._query(lon=lon, lat=lat, start=start, end=end, parameters=parameters)

        try:
            resp = self.client.get(url, params=query)
        except Exception as exc:
            raise ProviderError(f"NASA POWER request failed: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"NASA POWER returned HTTP {resp.status_code}: {resp.text[:250]}")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError("NASA POWER returned a non-JSON body") from exc
        props = payload.get("properties") or {}
        series = props.get("parameter") or {}
        if not series:
            raise ProviderError("NASA POWER response has no parameter series")
        progress(0.5, "downloaded NASA POWER series")

        fill = float((payload.get("header") or {}).get("fill_value", DEFAULT_FILL))
        meta_params = payload.get("parameters") or {}
        days = sorted({d for param in series.values() for d in param.keys()})

        workspace = params.dest_dir or new_workspace("raw")
        workspace.mkdir(parents=True, exist_ok=True)
        slug = f"power_{lat}_{lon}_{start.isoformat()}_{end.isoformat()}".replace(".", "p").replace("-", "")
        raw_path = workspace / f"{slug}.json"
        csv_path = workspace / f"{slug}.csv"
        raw_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")

        columns = list(parameters)
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["date", *columns])
            for day in days:
                row: list[Any] = [f"{day[:4]}-{day[4:6]}-{day[6:8]}"]
                for name in columns:
                    value = (series.get(name) or {}).get(day)
                    if value is None or float(value) == fill:
                        row.append("")
                    else:
                        row.append(float(value))
                writer.writerow(row)
        progress(1.0, "stored NASA POWER CSV")

        units = {name: (meta_params.get(name) or {}).get("units", "") for name in columns}
        longnames = {name: (meta_params.get(name) or {}).get("longname", "") for name in columns}
        try:
            start_iso = datetime.strptime(days[0], "%Y%m%d").date().isoformat() if days else start.isoformat()
        except ValueError:
            start_iso = start.isoformat()
        try:
            end_iso = datetime.strptime(days[-1], "%Y%m%d").date().isoformat() if days else end.isoformat()
        except ValueError:
            end_iso = end.isoformat()

        return FetchedArtifact(
            item=item,
            path=relative(workspace),
            size_bytes=csv_path.stat().st_size,
            checksum=file_checksum(csv_path),
            variables=columns,
            metadata={
                "format": "csv",
                "granules": [
                    {
                        "id": item.asset_id,
                        "date": start_iso,
                        "path": relative(csv_path),
                        "format": "csv",
                        "columns": columns,
                        "point": [lon, lat],
                    }
                ],
                "bands": {
                    name: {
                        "unit": units.get(name, ""),
                        "label": longnames.get(name, name),
                        "scale": 1.0,
                        "offset": 0.0,
                        "crs": None,
                        "resolution_m": None,
                        "resolution_note": "point sample at the study-area representative coordinate",
                        "bounds_wgs84": None,
                        "shape": None,
                    }
                    for name in columns
                },
                "sample_point": [lon, lat],
                "fill_value": fill,
                "fill_value_note": "fill values are stored as blanks (never coerced to zero)",
                "raw_path": relative(raw_path),
                "date_range": [start_iso, end_iso],
                "api_version": (payload.get("header") or {}).get("api", {}).get("version"),
                "sources": (payload.get("header") or {}).get("sources"),
            },
        )
