"""Microsoft Planetary Computer STAC adapters.

One adapter class per configured provider key; they share the STAC search /
SAS-signing machinery and differ by collection, band selection and the
documented scaling of each asset.

Endpoints (verified live, 2026-10-21):
  * STAC search   POST {stac_url}/search
  * SAS token     GET  {sas_url}/token/{collection}  -> {"token": "<query string>"}
The returned token is appended to asset hrefs (blob URLs are otherwise 403).
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

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
from app.providers.raster import (
    AssetRule,
    download_file,
    fetch_raster_band,
)

log = logging.getLogger("lakewatch.providers.mpc")

# Planetary Computer STAC item datetimes are ISO-8601 Z strings.
_SAS_CACHE_SECONDS = 35 * 60


def _parse_date(value: str | None, fallback: date | None) -> date | None:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return fallback


class MpcStacAdapter(ProviderAdapter):
    """Generic Planetary Computer collection adapter."""

    collection: str = ""
    stac_search_limit_cap: int = 100
    # asset key -> conversion rule (documented product scaling)
    asset_rules: dict[str, AssetRule] = {}
    # default asset selection for ingestion when the caller names none
    default_assets: list[str] = []
    qa_assets: list[str] = []

    # -- helpers ----------------------------------------------------------
    def _collection(self) -> str:
        return str(self.config.get("collection") or self.collection)

    def _stac_url(self) -> str:
        return str(self.config.get("stac_url") or settings.planetary_computer_stac_url).rstrip("/")

    def _sas_url(self) -> str:
        return str(self.config.get("sas_url") or settings.planetary_computer_sas_url).rstrip("/")

    def _search(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            resp = self.client.post(f"{self._stac_url()}/search", json=body)
        except Exception as exc:  # httpx transport errors
            raise ProviderError(f"STAC search unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderError(
                f"STAC search returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError("STAC search returned non-JSON body") from exc
        return list(payload.get("features") or [])

    def _sas_token(self) -> str:
        cached, expires = getattr(self, "_token", ""), getattr(self, "_token_expires", 0.0)
        if cached and time.time() < expires:
            return cached
        url = f"{self._sas_url()}/token/{self._collection()}"
        try:
            resp = self.client.get(url)
        except Exception as exc:
            raise ProviderError(f"SAS token endpoint unreachable: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderError(
                f"SAS token request returned HTTP {resp.status_code} for collection "
                f"'{self._collection()}': {resp.text[:200]}"
            )
        try:
            token = str(resp.json().get("token") or "")
        except ValueError as exc:
            raise ProviderError("SAS token endpoint returned non-JSON body") from exc
        if not token:
            raise ProviderError("SAS token endpoint returned an empty token")
        self._token = token
        self._token_expires = time.time() + _SAS_CACHE_SECONDS
        return token

    def sign_href(self, href: str) -> str:
        """Append the collection SAS token to an http(s) asset href."""
        if not href.startswith(("http://", "https://")):
            return href                      # local path (tests / mirrors)
        if "sig=" in urlparse(href).query:   # already signed
            return href
        token = self._sas_token()
        sep = "&" if "?" in href else "?"
        return f"{href}{sep}{token}"

    # -- ProviderAdapter API ----------------------------------------------
    def test_connection(self) -> TestResult:
        started = time.perf_counter()
        bbox = list(self.config.get("test_bbox") or [33.8, -14.7, 35.5, -9.6])
        body = {
            "collections": [self._collection()],
            "bbox": bbox,
            "datetime": "2024-01-01T00:00:00Z/2024-01-31T23:59:59Z",
            "limit": 1,
        }
        features = self._search(body)
        latency = int((time.perf_counter() - started) * 1000)
        message = (
            f"STAC search ok for collection '{self._collection()}' "
            f"({len(features)} item(s) in the sample window over the study area)"
        )
        return TestResult(ok=True, message=message, latency_ms=latency, details={"collection": self._collection()})

    def discover(self, params: IngestParams) -> list[DiscoveredItem]:
        collection = self._collection()
        limit = max(1, min(int(params.max_items or 20), self.stac_search_limit_cap))
        body: dict[str, Any] = {
            "collections": [collection],
            "datetime": (
                f"{params.start_date.isoformat()}T00:00:00Z/{params.end_date.isoformat()}T23:59:59Z"
            ),
            "limit": limit,
        }
        if params.bbox:
            body["bbox"] = list(params.bbox)
        features = self._search(body)

        items: list[DiscoveredItem] = []
        for feature in features:
            props = feature.get("properties") or {}
            asset_map = feature.get("assets") or {}
            if not asset_map:
                continue
            start = _parse_date(props.get("datetime"), None) or _parse_date(props.get("start_datetime"), None)
            end = _parse_date(props.get("datetime"), None) or _parse_date(props.get("end_datetime"), None)
            if start is None or end is None:
                # no usable datetime -> fall back to the requested window
                start, end = params.start_date, params.end_date
            item_id = str(feature.get("id") or props.get("id") or "")
            hrefs = {key: str(a.get("href") or "") for key, a in asset_map.items() if a.get("href")}
            asset_types = {key: str(a.get("type") or "") for key, a in asset_map.items()}
            bbox = feature.get("bbox")
            if bbox and len(bbox) == 4:
                bbox_t: tuple[float, float, float, float] | None = (
                    float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                )
            else:
                bbox_t = None
            items.append(
                DiscoveredItem(
                    asset_id=item_id,
                    title=f"{item_id}".strip() or collection,
                    start_date=start,
                    end_date=end,
                    bbox=bbox_t,
                    media_type="stac-item",
                    metadata={
                        "collection": collection,
                        "item_id": item_id,
                        "platform": props.get("platform") or props.get("constellation") or "",
                        "asset_types": asset_types,
                        "properties": {
                            k: props.get(k)
                            for k in ("eo:cloud_cover", "sza", "sat:orbit_state")
                            if k in props
                        },
                    },
                    assets=hrefs,
                )
            )
        items.sort(key=lambda it: (it.start_date or params.start_date, it.asset_id))
        return items

    def fetch(self, params: IngestParams, item: DiscoveredItem, progress: ProgressFn = _noop_progress) -> FetchedArtifact:
        from app.services.storage import new_workspace, relative

        requested = list(params.variables or [])
        selected = [k for k in (requested or self.default_assets) if k in item.assets]
        if not selected:
            selected = [k for k in self.default_assets if k in item.assets]
        if not selected:
            raise ProviderError(
                f"item '{item.asset_id}' exposes none of the requested assets "
                f"(requested={requested or self.default_assets}, available={sorted(item.assets)})"
            )
        # cloud/QA band is fetched alongside any optical selection (needed for masking)
        qa_added = False
        for qa_key in self.qa_assets:
            if qa_key in item.assets and qa_key not in selected:
                selected.append(qa_key)
                qa_added = True

        workspace = params.dest_dir or new_workspace("raw")
        workspace.mkdir(parents=True, exist_ok=True)
        max_dim = int((params.extra or {}).get("max_dim") or 2048)
        lat_ref = (params.bbox[1] + params.bbox[3]) / 2.0 if params.bbox else None

        bands: dict[str, Any] = {}
        stored: dict[str, str] = {}
        source_urls: dict[str, str] = {}
        total_size = 0
        n = len(selected)
        for idx, asset_key in enumerate(selected):
            href = item.assets[asset_key]
            rule = self.asset_rules.get(asset_key, AssetRule())
            source_urls[asset_key] = href
            signed = self.sign_href(href)
            suffix = _asset_suffix(href, asset_key)
            dest = workspace / f"{_slug(item.asset_id)}_{_slug(asset_key)}{suffix}"
            if _is_raster_suffix(suffix):
                try:
                    meta = fetch_raster_band(
                        signed,
                        dest,
                        native_name=asset_key,
                        bbox=params.bbox,
                        rule=rule,
                        max_dim=max_dim,
                        lat_ref=lat_ref,
                        extra_tags={"source_item": item.asset_id, "collection": self._collection()},
                    )
                except (ProviderError, OSError, ValueError):
                    # not raster-readable (or window failed): keep the raw asset
                    # whole so the data is still retrievable and auditable
                    size, _ = download_file(self.client, signed, dest)
                    total_size += size
                    stored[asset_key] = dest
                    bands[asset_key] = {
                        "crs": None,
                        "resolution_m": None,
                        "resolution_note": "raw asset stored whole (windowed read unavailable)",
                        "bounds_wgs84": None,
                        "shape": None,
                        "unit": rule.unit,
                        "label": rule.label,
                        "scale": 1.0,
                        "offset": 0.0,
                    }
                    progress((idx + 1) / n, f"retrieved {asset_key} (raw)")
                    continue
                stored[asset_key] = dest
                bands[asset_key] = {**meta, "unit": rule.unit, "label": rule.label, "scale": 1.0, "offset": 0.0}
            else:
                size, _ = download_file(self.client, signed, dest)
                total_size += size
                stored[asset_key] = dest
                bands[asset_key] = {
                    "crs": None,
                    "resolution_m": None,
                    "resolution_note": "non-raster asset; not windowed",
                    "bounds_wgs84": None,
                    "shape": None,
                    "unit": rule.unit,
                    "label": rule.label,
                    "scale": 1.0,
                    "offset": 0.0,
                }
            progress((idx + 1) / n, f"retrieved {asset_key}")

        size_total = sum(p.stat().st_size for p in stored.values() if p.exists())
        checksum = _combined_checksum(stored)
        granule_bands = {k: relative(p) for k, p in stored.items()}
        # a "geotiff" dataset only when every band was windowed into a GeoTIFF
        is_raster = bool(bands) and all(v.get("crs") for v in bands.values())
        artifact = FetchedArtifact(
            item=item,
            path=relative(workspace),
            size_bytes=size_total or total_size,
            checksum=checksum,
            variables=selected,
            metadata={
                "format": "geotiff" if is_raster else _container_format(selected, item),
                "granules": [
                    {
                        "id": item.asset_id,
                        "date": item.start_date.isoformat() if item.start_date else None,
                        "bands": granule_bands,
                    }
                ],
                "bands": bands,
                "collection": self._collection(),
                "qa_asset_added": qa_added,
                "max_dim": max_dim,
                "scene_bbox": list(item.bbox) if item.bbox else None,
                "source_urls": source_urls,
                "platform": item.metadata.get("platform", ""),
            },
        )
        return artifact


# ----------------------------------------------------------------------
def _slug(value: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-._" else "_" for c in (value or "item"))
    return keep.strip("._")[:90] or "item"


def _asset_suffix(href: str, asset_key: str) -> str:
    path = urlparse(href).path
    name = path.rsplit("/", 1)[-1] if path else asset_key
    if "." in name:
        ext = "." + name.rsplit(".", 1)[-1].lower()
        if ext in (".tif", ".tiff", ".jp2", ".json", ".xml", ".nc", ".nc4", ".bin", ".dat", ".txt"):
            return ext
        return ""
    return ""


def _is_raster_suffix(suffix: str) -> bool:
    return suffix in (".tif", ".tiff", ".jp2", "")


def _container_format(selected: list[str], item: DiscoveredItem) -> str:
    types = item.metadata.get("asset_types") or {}
    for key in selected:
        if "netcdf" in types.get(key, ""):
            return "netcdf"
        path = urlparse(item.assets.get(key, "")).path.lower()
        if path.endswith((".nc", ".nc4")):
            return "netcdf"
    return "geotiff"


def _combined_checksum(files: dict[str, Any]) -> str:
    import hashlib

    h = hashlib.sha256()
    for key in sorted(files):
        path = files[key]
        h.update(key.encode())
        try:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    h.update(chunk)
        except OSError:
            continue
    return h.hexdigest()


# ----------------------------------------------------------------------
# Sentinel-2 L2A (10/20/60 m surface reflectance)
S2_ASSETS = ["B02", "B03", "B04", "B08", "B11", "B12"]
S2_RULES = {
    # ESA L2A: reflectance = DN * 0.0001 (product specification, no offset)
    "B02": AssetRule(scale=0.0001, unit="reflectance", label="Blue (B02)", canonical="blue"),
    "B03": AssetRule(scale=0.0001, unit="reflectance", label="Green (B03)", canonical="green"),
    "B04": AssetRule(scale=0.0001, unit="reflectance", label="Red (B04)", canonical="red"),
    "B05": AssetRule(scale=0.0001, unit="reflectance", label="Red edge 1 (B05)", canonical="red_edge_1"),
    "B08": AssetRule(scale=0.0001, unit="reflectance", label="NIR (B08)", canonical="nir"),
    "B11": AssetRule(scale=0.0001, unit="reflectance", label="SWIR 1 (B11)", canonical="swir1"),
    "B12": AssetRule(scale=0.0001, unit="reflectance", label="SWIR 2 (B12)", canonical="swir2"),
    # scene classification: integer classes, never scaled, nearest resampling
    "SCL": AssetRule(unit="class", label="Scene classification (SCL)", resampling="nearest", qa=True, canonical="qa"),
}


class Sentinel2Mpc(MpcStacAdapter):
    key = "sentinel2_mpc"
    label = "Sentinel-2 L2A (Planetary Computer)"
    category = "sentinel2"
    product_type = "Sentinel-2 L2A surface reflectance (10-20 m)"
    description = (
        "ESA Sentinel-2 Level-2A surface reflectance via the Microsoft Planetary "
        "Computer STAC API. Assets are windowed to the study area at retrieval "
        "and scaled to reflectance (DN x 0.0001, ESA product specification)."
    )
    adapter_status = "tested"
    verification_note = "STAC search, SAS token signing and signed-asset access verified live (2026-10-21)."
    collection = "sentinel-2-l2a"
    default_assets = S2_ASSETS
    qa_assets = ["SCL"]
    asset_rules = S2_RULES
    capabilities = {
        "stac_search": True,
        "sas_signing": True,
        "spatial_filter": True,
        "temporal_filter": True,
        "raster": True,
        "optical": True,
        "optical_qa": True,
        "time_series": False,
    }
    default_variables = [
        {"key": k, "label": r.label, "unit": r.unit, "canonical": r.canonical}
        for k, r in S2_RULES.items()
    ]


# ----------------------------------------------------------------------
# Landsat Collection 2 Level-2 (30 m surface reflectance + 100 m thermal)
LANDSAT_ASSETS = ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7", "ST_B10"]
LANDSAT_RULES = {
    # USGS Landsat C2 L2: SR = DN * 2.75e-05 - 0.2 (surface reflectance)
    "SR_B2": AssetRule(scale=2.75e-05, offset=-0.2, unit="reflectance", label="Blue (SR_B2)", canonical="blue"),
    "SR_B3": AssetRule(scale=2.75e-05, offset=-0.2, unit="reflectance", label="Green (SR_B3)", canonical="green"),
    "SR_B4": AssetRule(scale=2.75e-05, offset=-0.2, unit="reflectance", label="Red (SR_B4)", canonical="red"),
    "SR_B5": AssetRule(scale=2.75e-05, offset=-0.2, unit="reflectance", label="NIR (SR_B5)", canonical="nir"),
    "SR_B6": AssetRule(scale=2.75e-05, offset=-0.2, unit="reflectance", label="SWIR 1 (SR_B6)", canonical="swir1"),
    "SR_B7": AssetRule(scale=2.75e-05, offset=-0.2, unit="reflectance", label="SWIR 2 (SR_B7)", canonical="swir2"),
    # USGS thermal scaling: T(K) = DN * 0.00341802 + 149.0
    "ST_B10": AssetRule(scale=0.00341802, offset=149.0, unit="K", label="Surface temperature (ST_B10)", canonical="thermal"),
    # QA bits: integer, never scaled
    "QA_PIXEL": AssetRule(unit="bits", label="Pixel QA (QA_PIXEL)", resampling="nearest", qa=True, canonical="qa"),
}


class LandsatMpc(MpcStacAdapter):
    key = "landsat_mpc"
    label = "Landsat C2 L2 (Planetary Computer)"
    category = "landsat"
    product_type = "Landsat Collection 2 Level-2 surface reflectance/temperature (30 m)"
    description = (
        "USGS Landsat Collection 2 Level-2 via the Microsoft Planetary Computer "
        "STAC API. Surface reflectance (DN x 2.75e-05 - 0.2) and thermal "
        "scalings follow the USGS product guide; QA_PIXEL is kept as bits."
    )
    adapter_status = "tested"
    verification_note = "STAC search, SAS token signing and signed-asset access verified live (2026-10-21)."
    collection = "landsat-c2-l2"
    default_assets = LANDSAT_ASSETS
    qa_assets = ["QA_PIXEL"]
    asset_rules = LANDSAT_RULES
    capabilities = {
        "stac_search": True,
        "sas_signing": True,
        "spatial_filter": True,
        "temporal_filter": True,
        "raster": True,
        "optical": True,
        "optical_qa": True,
        "thermal": True,
        "time_series": False,
    }
    default_variables = [
        {"key": k, "label": r.label, "unit": r.unit, "canonical": r.canonical}
        for k, r in LANDSAT_RULES.items()
    ]


# ----------------------------------------------------------------------
# MODIS MOD09A1 8-day surface reflectance (500 m)
MODIS_ASSETS = ["sur_refl_b01", "sur_refl_b02", "sur_refl_b03", "sur_refl_b04", "sur_refl_b06", "sur_refl_b07"]
MODIS_RULES = {
    # MOD09A1 collection 6.1: reflectance = DN * 0.0001
    "sur_refl_b01": AssetRule(scale=0.0001, unit="reflectance", label="Red (b01)", canonical="red"),
    "sur_refl_b02": AssetRule(scale=0.0001, unit="reflectance", label="NIR (b02)", canonical="nir"),
    "sur_refl_b03": AssetRule(scale=0.0001, unit="reflectance", label="Blue (b03)", canonical="blue"),
    "sur_refl_b04": AssetRule(scale=0.0001, unit="reflectance", label="Green (b04)", canonical="green"),
    "sur_refl_b06": AssetRule(scale=0.0001, unit="reflectance", label="SWIR 1 (b06)", canonical="swir1"),
    "sur_refl_b07": AssetRule(scale=0.0001, unit="reflectance", label="SWIR 2 (b07)", canonical="swir2"),
    "state_1km_16days": AssetRule(unit="bits", label="State QA (state_1km_16days)", resampling="nearest", qa=True, canonical="qa"),
}


class ModisMpc(MpcStacAdapter):
    key = "modis_mpc"
    label = "MODIS MOD09A1 (Planetary Computer)"
    category = "modis"
    product_type = "MODIS MOD09A1 8-day surface reflectance (500 m)"
    description = (
        "NASA MODIS MOD09A1 8-day surface reflectance (500 m) via the Microsoft "
        "Planetary Computer STAC API. Reflectance scaled DN x 0.0001 "
        "(MODIS C6.1 user guide); state QA band retained for cloud masking."
    )
    adapter_status = "tested"
    verification_note = "STAC search, SAS token signing and signed-asset access verified live (2026-10-21)."
    collection = "modis-09A1-061"
    default_assets = MODIS_ASSETS
    qa_assets = ["state_1km_16days"]
    asset_rules = MODIS_RULES
    capabilities = {
        "stac_search": True,
        "sas_signing": True,
        "spatial_filter": True,
        "temporal_filter": True,
        "raster": True,
        "optical": True,
        "optical_qa": True,
        "time_series": True,
    }
    default_variables = [
        {"key": k, "label": r.label, "unit": r.unit, "canonical": r.canonical}
        for k, r in MODIS_RULES.items()
    ]


# ----------------------------------------------------------------------
# MODIS MOD11A2 8-day land surface temperature (1 km)
MODIS_LST_RULES = {
    # MOD11A2 C6.1: LST(K) = DN * 0.02 (valid range 7500-65535)
    "LST_1km": AssetRule(scale=0.02, unit="K", label="Daytime LST (LST_1km)", canonical="thermal"),
    "QC_1km": AssetRule(unit="bits", label="LST QC (QC_1km)", resampling="nearest", qa=True, canonical="qa"),
}


class ModisLstMpc(MpcStacAdapter):
    key = "modis_lst_mpc"
    label = "MODIS MOD11A2 LST (Planetary Computer)"
    category = "satellite_temperature"
    product_type = "MODIS MOD11A2 8-day land/lake surface temperature (1 km)"
    description = (
        "NASA MODIS MOD11A2 8-day surface temperature (1 km) via the Microsoft "
        "Planetary Computer STAC API. LST(K) = DN x 0.02 (MODIS C6.1 user guide); "
        "QC band retained for quality masking."
    )
    adapter_status = "tested"
    verification_note = "STAC collection lookup verified live (2026-10-21); SAS signing shared with other MPC adapters."
    collection = "modis-11A2-061"
    default_assets = ["LST_1km"]
    qa_assets = ["QC_1km"]
    asset_rules = MODIS_LST_RULES
    capabilities = {
        "stac_search": True,
        "sas_signing": True,
        "spatial_filter": True,
        "temporal_filter": True,
        "raster": True,
        "thermal": True,
        "time_series": True,
    }
    default_variables = [
        {"key": k, "label": r.label, "unit": r.unit, "canonical": r.canonical}
        for k, r in MODIS_LST_RULES.items()
    ]


# ----------------------------------------------------------------------
# Sentinel-3 SRAL water-level (altimetry) netCDF
SRAL_RULES = {
    "wat_meas": AssetRule(unit="m", label="Water measurement (netCDF)", canonical="water_level"),
}


class Sentinel3SralMpc(MpcStacAdapter):
    key = "sentinel3_sral"
    label = "Sentinel-3 SRAL water level (Planetary Computer)"
    category = "satellite_altimetry"
    product_type = "Sentinel-3 SRAL water-level L2 (netCDF)"
    description = (
        "ESA Sentinel-3 SRAL water-body altimetry L2 product via the Microsoft "
        "Planetary Computer STAC API. The netCDF asset is downloaded whole "
        "(not a raster window); water-level values are read by indicator "
        "computation without rescaling."
    )
    adapter_status = "tested"
    verification_note = "STAC search, SAS token signing and signed-asset access verified live (2026-10-21)."
    collection = "sentinel-3-sral-wat-l2-netcdf"
    default_assets = ["wat_meas"]
    qa_assets = []
    asset_rules = SRAL_RULES
    capabilities = {
        "stac_search": True,
        "sas_signing": True,
        "spatial_filter": True,
        "temporal_filter": True,
        "raster": False,
        "netcdf": True,
        "altimetry": True,
        "time_series": False,
    }
    default_variables = [
        {"key": k, "label": r.label, "unit": r.unit, "canonical": r.canonical}
        for k, r in SRAL_RULES.items()
    ]
