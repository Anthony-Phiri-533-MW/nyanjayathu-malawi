"""First-run seeding: roles, permissions, default study area and indicator
definitions.  Idempotent - safe to call on every startup."""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import PERMISSIONS, ROLE_PERMISSIONS, SUPER_ADMIN
from app.models import IndicatorDefinition, Permission, Role, StudyArea, utcnow

log = logging.getLogger("lakewatch.bootstrap")

# Lake Malawi boundary (simplified polygon, WGS84) - used as the default study area.
LAKE_MALAWI_BOUNDARY = {
    "type": "Polygon",
    "coordinates": [
        [
            [33.88, -14.30],
            [34.10, -14.30],
            [34.45, -13.60],
            [34.90, -12.40],
            [35.05, -11.40],
            [35.25, -10.40],
            [35.35, -9.85],
            [34.95, -9.70],
            [34.60, -9.95],
            [34.30, -10.60],
            [34.85, -11.70],
            [34.75, -12.70],
            [34.45, -13.55],
            [34.95, -14.25],
            [34.98, -14.60],
            [34.65, -14.62],
            [34.20, -14.45],
            [33.88, -14.30],
        ]
    ],
}


def seed_roles_and_permissions(db: Session) -> None:
    existing = {p.key for p in db.execute(select(Permission)).scalars()}
    for key, (description, module) in PERMISSIONS.items():
        if key not in existing:
            db.add(Permission(key=key, description=description, module=module))
    db.flush()

    perms_by_key = {p.key: p for p in db.execute(select(Permission)).scalars()}
    role_names = set(db.execute(select(Role.name)).scalars())

    for name, keys in ROLE_PERMISSIONS.items():
        description = {
            SUPER_ADMIN: "Full system access",
            "admin": "Administrative access to users, sources, thresholds and audit logs",
            "researcher": "Research workspace access: datasets, jobs, indicators and exports",
        }[name]
        role = db.execute(select(Role).where(Role.name == name)).scalar_one_or_none()
        if role is None:
            role = Role(name=name, description=description, is_system=True)
            db.add(role)
            db.flush()
        role.permissions = [perms_by_key[k] for k in sorted(keys) if k in perms_by_key]
    log.info("Seeded roles/permissions (roles present: %s)", sorted(role_names | set(ROLE_PERMISSIONS)))


def seed_default_study_area(db: Session) -> None:
    exists = db.execute(select(func.count()).select_from(StudyArea)).scalar_one()
    if exists:
        return
    from app.services.spatial import geom_bbox, parse_geojson_geometry

    geom = parse_geojson_geometry(LAKE_MALAWI_BOUNDARY, allowed=["Polygon", "MultiPolygon"])
    minx, miny, maxx, maxy = geom_bbox(geom)
    db.add(
        StudyArea(
            name="Lake Malawi (lake extent)",
            description="Default study area covering the Lake Malawi basin shoreline polygon (WGS84).",
            boundary_geojson=LAKE_MALAWI_BOUNDARY,
            minx=minx,
            miny=miny,
            maxx=maxx,
            maxy=maxy,
            is_default=True,
        )
    )


# key, name, category, unit, description, definition, method, version, is_proxy
INDICATOR_DEFINITIONS: list[tuple[dict, ...]] = [
    (
        {
            "key": "water_extent",
            "name": "Water extent",
            "category": "water_level",
            "unit": "km²",
            "is_proxy": False,
            "requires": ["observed", "composite"],
            "description": "Mapped surface-water area within the study area for an observation date.",
            "definition": (
                "Area of pixels classified as water (MNDWI > threshold) inside the study-area boundary, "
                "excluding cloud/shadow/nodata pixels. Water extent is a planimetric area - it is NOT a "
                "direct water-level measurement."
            ),
            "method": (
                "MNDWI = (Green - SWIR1) / (Green + SWIR1) after Xu (2006); water where MNDWI > 0 "
                "(threshold provisional, configurable). Pixel areas computed in the source CRS "
                "(geodesic rows for geographic CRS). Cloud masking uses S2 scene-classification or "
                "Landsat QA_PIXEL where available."
            ),
            "method_version": "1.0.0",
        },
    ),
    (
        {
            "key": "water_extent_change",
            "name": "Change in water extent",
            "category": "water_level",
            "unit": "km²",
            "is_proxy": False,
            "requires": ["observed", "composite"],
            "description": "Difference in mapped water extent between consecutive valid observations.",
            "definition": (
                "water_extent(t2) - water_extent(t1) for consecutive observations with valid coverage; "
                "positive means larger mapped extent at t2."
            ),
            "method": (
                "Derived from water_extent results computed with method version 1.0.0; only pairs where "
                "both observations passed quality rules are differenced."
            ),
            "method_version": "1.0.0",
        },
    ),
    (
        {
            "key": "water_level_altimetry",
            "name": "Satellite altimetry water level",
            "category": "water_level",
            "unit": "m",
            "is_proxy": False,
            "requires": ["altimetry"],
            "description": "Water-level observation derived from a satellite-altimetry dataset.",
            "definition": (
                "Water level (relative to the reference ellipsoid or datum recorded in the source "
                "dataset) at an overpass time, as provided by the altimetry product."
            ),
            "method": (
                "Computed only when a satellite-altimetry dataset has been ingested; values and datum "
                "are taken from the source product unchanged. No altimetry values are synthesised."
            ),
            "method_version": "1.0.0",
        },
    ),
    (
        {
            "key": "chlorophyll_a_proxy",
            "name": "Chlorophyll-a proxy",
            "category": "water_quality",
            "unit": "index",
            "is_proxy": True,
            "requires": ["observed", "composite"],
            "description": "Unvalidated optical proxy for chlorophyll-a concentration.",
            "definition": (
                "Normalised red/green reflectance band ratio computed on clear water pixels: "
                "R/G ratio in [0, ~2]. Higher values suggest higher chlorophyll-a but the index is "
                "unitless and is NOT a calibrated concentration."
            ),
            "method": (
                "Band-ratio proxy on atmospherically uncorrected surface reflectance (Level-2 where "
                "available). NOT validated against in-situ chlorophyll-a for Lake Malawi; treat as a "
                "relative indicator only. Flagged UNVALIDATED."
            ),
            "method_version": "1.0.0",
        },
    ),
    (
        {
            "key": "turbidity_proxy",
            "name": "Turbidity / suspended-material proxy (NDTI)",
            "category": "water_quality",
            "unit": "index",
            "is_proxy": True,
            "requires": ["observed", "composite"],
            "description": "Normalised difference turbidity index - a suspended-sediment proxy.",
            "definition": (
                "NDTI = (Red - Green) / (Red + Green) on clear water pixels (normalised difference "
                "turbidity index; Lymburner et al., 2016, Remote Sensing of Environment)."
            ),
            "method": (
                "NDTI computed from surface reflectance; positive values indicate higher sediment "
                "load relative to the reference. Not validated for Lake Malawi; flagged UNVALIDATED."
            ),
            "method_version": "1.0.0",
        },
    ),
    (
        {
            "key": "surface_water_temperature",
            "name": "Surface-water temperature",
            "category": "water_quality",
            "unit": "°C",
            "is_proxy": False,
            "requires": ["thermal"],
            "description": "Lake surface temperature from a thermal infrared band.",
            "definition": (
                "Brightness/skin temperature from the surface-temperature band of an optical-thermal "
                "product (e.g. Landsat Collection 2 Level-2 ST_B10) over clear water pixels."
            ),
            "method": (
                "Landsat Collection 2 Level-2 ST scaling: T(K) = DN × 0.00341802 + 149.0 "
                "(USGS documented scaling), converted to °C. Cloudy pixels excluded. Only products "
                "carrying a thermal band are eligible."
            ),
            "method_version": "1.0.0",
        },
    ),
    (
        {
            "key": "rainfall_summary",
            "name": "Rainfall summary",
            "category": "climate",
            "unit": "mm",
            "is_proxy": False,
            "requires": ["precipitation"],
            "description": "Total (or mean) rainfall over a period and study area.",
            "definition": "Sum of daily precipitation over the requested period, averaged across "
            "valid study-area pixels (area-weighted mean per day, then summed).",
            "method": (
                "Gridded satellite rainfall (e.g. CHIRPS v2.0 daily 0.05°) windowed to the study "
                "area; nodata pixels excluded. Aggregation = sum of daily area means."
            ),
            "method_version": "1.0.0",
        },
    ),
    (
        {
            "key": "rainfall_anomaly",
            "name": "Rainfall anomaly",
            "category": "climate",
            "unit": "mm",
            "is_proxy": False,
            "requires": ["precipitation"],
            "description": "Period rainfall total minus baseline-period total.",
            "definition": "anomaly = period_total - baseline_total over the same study area.",
            "method": (
                "Baseline period is supplied in compute parameters (baseline_start/baseline_end); "
                "when absent, the baseline is the mean of available comparable period totals already "
                "computed in this system. The baseline actually used is recorded in provenance. "
                "This is not an official climatology."
            ),
            "method_version": "1.0.0",
        },
    ),
    (
        {
            "key": "temperature_summary",
            "name": "Air temperature summary",
            "category": "climate",
            "unit": "°C",
            "is_proxy": False,
            "requires": ["temperature"],
            "description": "Mean 2 m air temperature over a period for the study-area point/region.",
            "definition": "Mean of daily 2 m air temperature (T2M) over the requested period.",
            "method": (
                "NASA POWER daily point series sampled at the study-area representative coordinate; "
                "point source - not a lake-surface temperature. Provenance records the coordinates."
            ),
            "method_version": "1.0.0",
        },
    ),
    (
        {
            "key": "temperature_anomaly",
            "name": "Air temperature anomaly",
            "category": "climate",
            "unit": "°C",
            "is_proxy": False,
            "requires": ["temperature"],
            "description": "Period mean temperature minus baseline-period mean.",
            "definition": "anomaly = period_mean - baseline_mean (°C).",
            "method": (
                "Baseline supplied in compute parameters or derived from available computed period "
                "means; the baseline used is recorded in provenance. Not an official climatology."
            ),
            "method_version": "1.0.0",
        },
    ),
]


def seed_indicator_definitions(db: Session) -> None:
    for spec_tuple in INDICATOR_DEFINITIONS:
        spec = spec_tuple[0]
        existing = db.execute(
            select(IndicatorDefinition).where(IndicatorDefinition.key == spec["key"])
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                IndicatorDefinition(
                    key=spec["key"],
                    name=spec["name"],
                    category=spec["category"],
                    description=spec["description"],
                    definition=spec["definition"],
                    unit=spec["unit"],
                    method=spec["method"],
                    method_version=spec["method_version"],
                    is_proxy=spec["is_proxy"],
                    requires_kinds=spec["requires"],
                    is_enabled=True,
                    created_at=utcnow(),
                )
            )


def run_bootstrap(db: Session) -> None:
    seed_roles_and_permissions(db)
    seed_default_study_area(db)
    seed_indicator_definitions(db)
    db.commit()
