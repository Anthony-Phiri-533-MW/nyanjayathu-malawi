"""Inference for the locally supplied Lake Malawi regression artifacts.

The serialized files are trusted, project-local joblib artifacts. They are
loaded only from the fixed ``backend/ml-models`` directory and only when a
prediction is requested.
"""
from __future__ import annotations

import importlib.util
import logging
import math
import sys
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.errors import NotFoundError, ServiceUnavailableError, UnprocessableError

log = logging.getLogger("lakewatch.local_models")
MODEL_DIR = Path(__file__).resolve().parents[2] / "ml-models"
ARTIFACT_SKLEARN_VERSION = "1.6.1"


class TrendResidualCoupledRegressor:
    """Compatibility class required by the local TRC-ML joblib artifact."""

    def predict(self, features: np.ndarray) -> np.ndarray:
        return self.trend_model.predict(features) + self.residual_model.predict(features)


_TURBIDITY_FEATURES = (
    ("air_temp_c", "Air temperature", "°C"),
    ("precipitation_mm", "Daily precipitation", "mm"),
    ("wind_speed_m_s", "Wind speed", "m/s"),
    ("solar_radiation_wm2", "Solar radiation", "W/m²"),
)
_TEMPERATURE_FEATURES = (
    ("precipitation", "Current precipitation", "mm"),
    ("wind_speed", "Current wind speed", "m/s"),
    ("temp_lag_1", "Temperature, 1-day lag", "°C"),
    ("wind_lag_1", "Wind speed, 1-day lag", "m/s"),
    ("precip_lag_1", "Precipitation, 1-day lag", "mm"),
    ("temp_lag_2", "Temperature, 2-day lag", "°C"),
    ("wind_lag_2", "Wind speed, 2-day lag", "m/s"),
    ("precip_lag_2", "Precipitation, 2-day lag", "mm"),
    ("temp_lag_7", "Temperature, 7-day lag", "°C"),
    ("wind_lag_7", "Wind speed, 7-day lag", "m/s"),
    ("precip_lag_7", "Precipitation, 7-day lag", "mm"),
    ("temp_lag_14", "Temperature, 14-day lag", "°C"),
    ("wind_lag_14", "Wind speed, 14-day lag", "m/s"),
    ("precip_lag_14", "Precipitation, 14-day lag", "mm"),
    ("sin_day", "Day-of-year sine", "unitless"),
    ("cos_day", "Day-of-year cosine", "unitless"),
)
_WATER_EXTENT_FEATURES = (
    ("sin_day", "Day-of-year sine", "unitless"),
    ("cos_day", "Day-of-year cosine", "unitless"),
    ("water_level_lag_1", "Training target value, 1-day lag", "unverified training unit"),
    ("water_level_lag_2", "Training target value, 2-day lag", "unverified training unit"),
    ("water_level_lag_7", "Training target value, 7-day lag", "unverified training unit"),
    ("water_level_lag_14", "Training target value, 14-day lag", "unverified training unit"),
    ("precip_lag_1", "Precipitation, 1-day lag", "mm"),
    ("precip_lag_7", "Precipitation, 7-day lag", "mm"),
    ("surface_temp", "Surface temperature", "°C"),
    ("wind_speed", "Wind speed", "m/s"),
)

_MODEL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "turbidity": {
        "name": "Lake Malawi turbidity predictor",
        "target": "Turbidity",
        "unit": "NTU",
        "artifact": Path("tubidity") / "lake_malawi_turbidity_model.joblib",
        "features": _TURBIDITY_FEATURES,
        "dependencies": ("joblib", "sklearn"),
        "metrics": {"r2": 0.91, "rmse": 3.09},
        "metrics_note": "Values reported in the supplied model README; not independently verified.",
    },
    "surface_temperature": {
        "name": "Lake Malawi surface temperature ensemble",
        "target": "Surface temperature",
        "unit": "°C",
        "artifact": Path("surace-temps") / "lake_malawi_temp_ensemble_model.joblib",
        "features": _TEMPERATURE_FEATURES,
        "dependencies": ("joblib", "sklearn", "xgboost"),
        "metrics": {"mae": 0.242, "rmse": 0.307},
        "metrics_note": "Values reported in the supplied model README; not independently verified.",
    },
    "water_extent": {
        "name": "Lake Malawi water-level/extent TRC-ML",
        "target": "Water-level/extent training target (definition unverified)",
        "unit": "unverified training unit",
        "artifact": Path("water-level-extent") / "lake_malawi_trc_ml_model.joblib",
        "scaler": Path("water-level-extent") / "lake_malawi_scaler.joblib",
        "features": _WATER_EXTENT_FEATURES,
        "dependencies": ("joblib", "sklearn"),
        "metrics": None,
        "metrics_note": "No validation metrics were supplied.",
    },
}


def _missing_dependencies(dependencies: tuple[str, ...]) -> list[str]:
    missing = [name for name in dependencies if importlib.util.find_spec(name) is None]
    if "sklearn" in dependencies and "sklearn" not in missing:
        try:
            installed = version("scikit-learn")
        except PackageNotFoundError:
            missing.append("scikit-learn")
        else:
            if installed != ARTIFACT_SKLEARN_VERSION:
                missing.append(f"scikit-learn=={ARTIFACT_SKLEARN_VERSION} (installed {installed})")
    return missing


def _artifact_paths(definition: dict[str, Any]) -> list[Path]:
    return [MODEL_DIR / definition[key] for key in ("artifact", "scaler") if key in definition]


def list_local_models() -> list[dict[str, Any]]:
    """Return local model metadata and availability without deserializing artifacts."""
    models = []
    for key, definition in _MODEL_DEFINITIONS.items():
        missing_files = [path.name for path in _artifact_paths(definition) if not path.is_file()]
        missing_dependencies = _missing_dependencies(definition["dependencies"])
        reasons = []
        if missing_files:
            reasons.append(f"Missing artifact file(s): {', '.join(missing_files)}")
        if missing_dependencies:
            reasons.append(f"Missing runtime package(s): {', '.join(missing_dependencies)}")
        models.append(
            {
                "key": key,
                "name": definition["name"],
                "target": definition["target"],
                "unit": definition["unit"],
                "features": [
                    {"key": feature, "label": label, "unit": unit}
                    for feature, label, unit in definition["features"]
                ],
                "metrics": definition["metrics"],
                "metrics_note": definition["metrics_note"],
                "ready": not reasons,
                "unavailable_reason": "; ".join(reasons) or None,
            }
        )
    return models


@lru_cache(maxsize=len(_MODEL_DEFINITIONS))
def _load_model(key: str) -> Any:
    definition = _MODEL_DEFINITIONS[key]
    missing_dependencies = _missing_dependencies(definition["dependencies"])
    if missing_dependencies:
        raise ServiceUnavailableError(
            "The local model runtime is not installed",
            details={"missing_dependencies": missing_dependencies},
        )
    missing_files = [str(path.relative_to(MODEL_DIR)) for path in _artifact_paths(definition) if not path.is_file()]
    if missing_files:
        raise ServiceUnavailableError(
            "The local model artifact is missing",
            details={"missing_artifacts": missing_files},
        )

    import joblib

    if key == "water_extent":
        # This artifact was serialized from a notebook's __main__ module.
        setattr(sys.modules["__main__"], "TrendResidualCoupledRegressor", TrendResidualCoupledRegressor)
        return (
            joblib.load(MODEL_DIR / definition["artifact"]),
            joblib.load(MODEL_DIR / definition["scaler"]),
        )
    return joblib.load(MODEL_DIR / definition["artifact"])


def _ordered_features(key: str, features: dict[str, float]) -> list[float]:
    expected = [name for name, _, _ in _MODEL_DEFINITIONS[key]["features"]]
    missing = [name for name in expected if name not in features]
    extra = sorted(set(features) - set(expected))
    invalid = [name for name in expected if name in features and not math.isfinite(features[name])]
    if missing or extra or invalid:
        raise UnprocessableError(
            "Input features must exactly match the selected model schema and contain finite numbers",
            details={"missing": missing, "unexpected": extra, "non_finite": invalid},
        )
    return [float(features[name]) for name in expected]


def predict_local_model(key: str, features: dict[str, float]) -> dict[str, Any]:
    """Run one local model using explicit feature values supplied by the caller."""
    definition = _MODEL_DEFINITIONS.get(key)
    if definition is None:
        raise NotFoundError(f"Unknown local model '{key}'")
    values = _ordered_features(key, features)
    try:
        model = _load_model(key)
        if key == "turbidity":
            columns = [name for name, _, _ in definition["features"]]
            prediction = model.predict(
                pd.DataFrame([dict(zip(columns, values, strict=True))])
            )[0]
        elif key == "surface_temperature":
            feature_names = model["features"]
            expected = [name for name, _, _ in definition["features"]]
            if list(feature_names) != expected:
                raise ServiceUnavailableError(
                    "The temperature model's embedded feature order does not match its documented schema",
                    details={"embedded_features": list(feature_names)},
                )
            frame = pd.DataFrame([dict(zip(expected, values, strict=True))])[feature_names]
            scaled = model["scaler"].transform(frame)
            weights = model["ensemble_weights"]
            prediction = sum(
                float(weights[member]) * float(model[f"{member}_model"].predict(scaled)[0])
                for member in ("rf", "gb", "xgb")
            )
        else:
            estimator, scaler = model
            columns = [name for name, _, _ in definition["features"]]
            frame = pd.DataFrame([dict(zip(columns, values, strict=True))])
            scaled = scaler.transform(frame)
            prediction = estimator.predict(scaled)[0]
    except ServiceUnavailableError:
        raise
    except Exception as exc:
        log.exception("Local model inference failed for %s", key)
        raise ServiceUnavailableError(
            f"Could not run the local {definition['name']} model",
            details={"reason": f"{type(exc).__name__}: {exc}"},
        ) from exc

    value = float(prediction)
    if not math.isfinite(value):
        raise ServiceUnavailableError("The local model returned a non-finite prediction")
    return {
        "model_key": key,
        "model_name": definition["name"],
        "target": definition["target"],
        "unit": definition["unit"],
        "value": value,
        "features": features,
    }
