"""Catalogue of supported preprocessing operations (used by the API + UI)."""
from __future__ import annotations

PROCESSING_OPERATIONS: dict[str, dict] = {
    "validate": {
        "label": "Input validation",
        "description": (
            "Check CRS presence, band availability, nodata declaration, resolution "
            "and AOI intersection of the input dataset before further processing."
        ),
        "params": [],
        "writes_product": False,
        "requires": [],
    },
    "clip": {
        "label": "Clip to study area",
        "description": "Mask everything outside the study-area boundary (pixels outside become nodata).",
        "params": [
            {"name": "all_touched", "type": "bool", "default": False, "description": "Include boundary-touching pixels"}
        ],
        "writes_product": True,
        "requires": [],
    },
    "reproject": {
        "label": "Reproject (CRS)",
        "description": "Reproject the raster to a target coordinate reference system.",
        "params": [
            {"name": "dst_crs", "type": "str", "default": "EPSG:4326", "description": "Target CRS, e.g. EPSG:32736"},
            {"name": "resampling", "type": "str", "default": "bilinear", "description": "nearest|bilinear|cubic|average"},
        ],
        "writes_product": True,
        "requires": [],
    },
    "resample": {
        "label": "Resample resolution",
        "description": "Resample to a target grid resolution in metres (projected CRS required).",
        "params": [
            {"name": "resolution_m", "type": "float", "default": None, "description": "Target resolution in metres"},
            {"name": "resampling", "type": "str", "default": "bilinear", "description": "Resampling method"},
        ],
        "writes_product": True,
        "requires": [],
    },
    "cloud_mask": {
        "label": "Cloud & shadow mask",
        "description": (
            "Mask clouds, cloud shadows, cirrus and snow using the sensor QA product "
            "(Sentinel-2 SCL classes or Landsat QA_PIXEL bits)."
        ),
        "params": [],
        "writes_product": True,
        "requires": ["optical_qa"],
    },
    "water_mask": {
        "label": "Water mask",
        "description": "Classify water with MNDWI (Xu 2006) or NDWI (McFeeters 1996).",
        "params": [
            {"name": "method", "type": "str", "default": "mndwi", "description": "mndwi|ndwi"},
            {"name": "threshold", "type": "float", "default": 0.0, "description": "Index threshold (provisional default 0.0)"},
        ],
        "writes_product": True,
        "requires": ["green"],
    },
    "harmonize": {
        "label": "Cross-sensor adjustment",
        "description": (
            "Apply a user-supplied linear gain/offset adjustment per canonical band. "
            "Requires a citable reference; identity is applied when no adjustment is supplied "
            "(and the run records harmonisation_applied=false)."
        ),
        "params": [
            {"name": "gains", "type": "dict", "default": {}, "description": "band -> gain"},
            {"name": "offsets", "type": "dict", "default": {}, "description": "band -> offset"},
            {"name": "reference", "type": "str", "default": "", "description": "Citable source for the coefficients"},
        ],
        "writes_product": True,
        "requires": [],
    },
    "temporal_composite": {
        "label": "Temporal composite",
        "description": (
            "Combine aligned observations across dates into one product "
            "(median/mean/max/min/percentile, nodata-aware)."
        ),
        "params": [
            {"name": "method", "type": "str", "default": "median", "description": "median|mean|max|min|percentile"},
            {"name": "percentile", "type": "float", "default": 75.0, "description": "Used when method=percentile"},
            {"name": "band", "type": "str", "default": "", "description": "Composite a single band key only"},
        ],
        "writes_product": True,
        "requires": ["multi_dataset"],
    },
    "missing_data": {
        "label": "Missing-data assessment",
        "description": "Compute valid/missing pixel fractions against the study-area footprint (metrics only).",
        "params": [],
        "writes_product": False,
        "requires": [],
    },
    "quality_flags": {
        "label": "Quality-flag generation",
        "description": (
            "Run the explicit quality rules (VALID / LOW_QUALITY / INSUFFICIENT_COVERAGE / "
            "CLOUD_CONTAMINATED / MISSING_DATA / PROCESSING_FAILED / UNVALIDATED) "
            "and persist an assessment for the product."
        ),
        "params": [],
        "writes_product": False,
        "requires": [],
    },
}
