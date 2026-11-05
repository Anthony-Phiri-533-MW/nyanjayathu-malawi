"""Short-term forecasting engine.

Design
------
* **Data** - the only input is persisted ``IndicatorResult`` rows.  A series is
  placed on a regular cadence (daily / weekly / monthly) inferred from the
  median observation gap, so satellite revisit gaps do not create phantom
  values.
* **Models** - real, fitted estimators: random forest, histogram gradient
  boosting and ridge regression (plus XGBoost when installed).  A persistence
  ("last value") forecast is kept as the skill benchmark, never as the
  headline model.
* **Validation** - blocked rolling-origin backtesting.  Each fold trains only
  on data *before* its origin and tests on the following ``test_size`` steps,
  which is the temporal validation protocol required by the project
  methodology.  No random shuffling and no leakage across folds.
* **Uncertainty** - a Gaussian residual interval whose width grows with
  ``sqrt(lead)``; empirical coverage is reported for every fold.
* **Honesty** - a series shorter than the configured minimum produces a
  ``skipped`` run and **no** forecast rows.  Nothing is interpolated into a
  number that the data cannot support.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import pickle
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any, Protocol

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, UnprocessableError
from app.models import (
    ForecastRun,
    ForecastValue,
    IndicatorDefinition,
    IndicatorResult,
    MLModel,
    ModelEvaluation,
    StudyArea,
    User,
    utcnow,
)
from app.services import audit as audit_service
from app.services.jobs import JobContext, register_handler

log = logging.getLogger("lakewatch.forecasting")

try:  # pragma: no cover - exercised only when the dependency is installed
    from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    SKLEARN_AVAILABLE = True
except Exception:  # noqa: BLE001 - optional dependency
    SKLEARN_AVAILABLE = False

try:  # pragma: no cover - optional
    from xgboost import XGBRegressor

    XGBOOST_AVAILABLE = True
except Exception:  # noqa: BLE001
    XGBOOST_AVAILABLE = False


# --------------------------------------------------------------------- models
class Predictor(Protocol):
    def fit(self, X: np.ndarray, y: np.ndarray) -> "Predictor": ...
    def predict(self, X: np.ndarray) -> np.ndarray: ...


class NumpyRidge:
    """Small dependency-free ridge regression used when scikit-learn is absent.

    It is a genuine fitted linear model (closed-form least squares with an
    L2 penalty), not a placeholder, and it keeps the pipeline operational on a
    minimal deployment.
    """

    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = alpha
        self.coef_: np.ndarray | None = None
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "NumpyRidge":
        X = np.asarray(X, dtype=float)
        self.mean_ = X.mean(axis=0)
        self.scale_ = X.std(axis=0)
        self.scale_[self.scale_ == 0] = 1.0
        Z = np.hstack([np.ones((len(X), 1)), (X - self.mean_) / self.scale_])
        penalty = np.eye(Z.shape[1]) * self.alpha
        penalty[0, 0] = 0.0
        self.coef_ = np.linalg.solve(Z.T @ Z + penalty, Z.T @ y)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.coef_ is None:
            raise RuntimeError("NumpyRidge is not fitted")
        X = np.asarray(X, dtype=float)
        Z = np.hstack([np.ones((len(X), 1)), (X - self.mean_) / self.scale_])
        return Z @ self.coef_


def _make_estimator(algorithm: str, n_samples: int):
    if algorithm == "random_forest":
        if not SKLEARN_AVAILABLE:
            raise UnprocessableError("random_forest requires scikit-learn to be installed")
        return RandomForestRegressor(
            n_estimators=400 if n_samples >= 120 else 200,
            min_samples_leaf=1 if n_samples < 60 else 2,
            max_features=0.6,
            random_state=42,
            n_jobs=-1,
        )
    if algorithm == "gradient_boosting":
        if not SKLEARN_AVAILABLE:
            raise UnprocessableError("gradient_boosting requires scikit-learn to be installed")
        return HistGradientBoostingRegressor(
            max_iter=400,
            learning_rate=0.05,
            max_depth=None,
            min_samples_leaf=max(3, n_samples // 40),
            l2_regularization=1.0,
            random_state=42,
        )
    if algorithm == "ridge":
        if not SKLEARN_AVAILABLE:
            return NumpyRidge(alpha=1.0)
        return Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=1.0))])
    if algorithm == "xgboost":
        if not XGBOOST_AVAILABLE:
            raise UnprocessableError("xgboost is not installed")
        return XGBRegressor(
            n_estimators=400,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=-1,
        )
    raise UnprocessableError(f"Unknown forecasting algorithm '{algorithm}'")


def available_algorithms() -> list[str]:
    algorithms = ["ridge", "gradient_boosting", "random_forest"]
    if XGBOOST_AVAILABLE:
        algorithms.append("xgboost")
    return algorithms


# ---------------------------------------------------------------------- data
@dataclass
class Series:
    indicator_key: str
    study_area_id: int
    unit: str
    cadence: str
    values: np.ndarray
    dates: list[date]

    @property
    def n(self) -> int:
        return len(self.values)


@dataclass
class FoldResult:
    fold: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    n_train: int
    n_test: int
    rmse: float
    mae: float
    bias: float
    mape: float | None
    r2: float | None
    skill_score: float | None
    coverage: float | None


@dataclass
class AlgorithmScore:
    algorithm: str
    folds: list[FoldResult] = field(default_factory=list)
    sigma: float = 0.0

    def aggregate(self) -> dict[str, float | None]:
        def mean_metric(name: str) -> float | None:
            vals = [getattr(f, name) for f in self.folds if getattr(f, name) is not None]
            return float(np.mean(vals)) if vals else None

        def std_metric(name: str) -> float | None:
            vals = [getattr(f, name) for f in self.folds if getattr(f, name) is not None]
            return float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0

        return {
            "rmse": mean_metric("rmse"),
            "rmse_std": std_metric("rmse"),
            "mae": mean_metric("mae"),
            "mae_std": std_metric("mae"),
            "bias": mean_metric("bias"),
            "bias_std": std_metric("bias"),
            "mape": mean_metric("mape"),
            "r2": mean_metric("r2"),
            "skill_score": mean_metric("skill_score"),
            "coverage": mean_metric("coverage"),
            "sigma": self.sigma,
            "n_folds": len(self.folds),
        }


def _infer_cadence(dates: list[date]) -> tuple[str, str]:
    if len(dates) < 2:
        return "daily", "D"
    gaps = np.array([(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0])
    if gaps.size == 0:
        return "daily", "D"
    median = float(np.median(gaps))
    if median <= 2:
        return "daily", "D"
    if median <= 10:
        return "weekly", "W"
    return "monthly", "MS"


def load_series(
    db: Session, *, study_area_id: int, indicator_key: str
) -> Series:
    """Assemble one regularised indicator series from persisted results."""
    rows = db.execute(
        select(IndicatorResult.observed_end, IndicatorResult.value, IndicatorResult.unit)
        .where(
            IndicatorResult.study_area_id == study_area_id,
            IndicatorResult.indicator_key == indicator_key,
            IndicatorResult.value.is_not(None),
        )
        .order_by(IndicatorResult.observed_end.asc(), IndicatorResult.id.asc())
    ).all()
    if not rows:
        raise NotFoundError(
            f"No computed '{indicator_key}' results for study area {study_area_id}"
        )

    raw = pd.DataFrame(rows, columns=["date", "value", "unit"])
    raw["date"] = pd.to_datetime(raw["date"])
    # Duplicate dates (several scenes in one period) are averaged; this is a
    # stated aggregation rule, not an imputation.
    grouped = raw.groupby("date", as_index=False)["value"].mean()
    grouped = grouped.sort_values("date")

    cadence, freq = _infer_cadence(list(grouped["date"].dt.date))
    if cadence != "daily":
        grouped = (
            grouped.set_index("date")["value"]
            .resample(freq)
            .mean()
            .dropna()
            .reset_index()
        )
    unit = str(rows[-1].unit or "")
    return Series(
        indicator_key=indicator_key,
        study_area_id=study_area_id,
        unit=unit,
        cadence=cadence,
        values=grouped["value"].to_numpy(dtype=float),
        dates=[d.date() if hasattr(d, "date") else d for d in grouped["date"]],
    )


# ------------------------------------------------------------------ features
DEFAULT_LAGS = 3
ROLLING_WINDOWS = (3, 7)
FEATURE_COUNT = DEFAULT_LAGS + 2 * len(ROLLING_WINDOWS) + 3


def _feature_row(history: list[float], when: date) -> list[float]:
    row: list[float] = []
    for lag in range(1, DEFAULT_LAGS + 1):
        row.append(history[-lag] if len(history) >= lag else float("nan"))
    for window in ROLLING_WINDOWS:
        chunk = history[-window:]
        row.append(float(np.nanmean(chunk)) if chunk else float("nan"))
        row.append(float(np.nanstd(chunk)) if len(chunk) > 1 else 0.0)
    doy = when.timetuple().tm_yday
    row.extend([math.sin(2 * math.pi * doy / 365.25), math.cos(2 * math.pi * doy / 365.25)])
    row.append(float(len(history)))  # monotone trend proxy
    return row


def _design_matrix(values: np.ndarray, dates: list[date]) -> tuple[np.ndarray, np.ndarray]:
    X: list[list[float]] = []
    y: list[float] = []
    history: list[float] = []
    for value, when in zip(values, dates):
        if len(history) >= DEFAULT_LAGS:
            X.append(_feature_row(history, when))
            y.append(float(value))
        history.append(float(value))
    if not X:
        return np.empty((0, FEATURE_COUNT)), np.empty((0,))
    Xa = np.asarray(X, dtype=float)
    # Median imputation for the first rolling windows; never silently zero.
    col_median = np.nanmedian(Xa, axis=0)
    col_median = np.where(np.isnan(col_median), 0.0, col_median)
    idx = np.where(np.isnan(Xa))
    Xa[idx] = np.take(col_median, idx[1])
    return Xa, np.asarray(y, dtype=float)


def recursive_forecast(
    estimator: Predictor, values: np.ndarray, dates: list[date], steps: int, cadence: str
) -> tuple[list[float], list[date]]:
    history = [float(v) for v in values]
    preds: list[float] = []
    out_dates: list[date] = []
    last = dates[-1]
    for _ in range(steps):
        last = _next_period(last, cadence)
        row = np.asarray([_feature_row(history, last)], dtype=float)
        pred = float(np.asarray(estimator.predict(row)).ravel()[0])
        preds.append(pred)
        out_dates.append(last)
        history.append(pred)
    return preds, out_dates


def _next_period(day: date, cadence: str) -> date:
    if cadence == "daily":
        return date.fromordinal(day.toordinal() + 1)
    if cadence == "weekly":
        return date.fromordinal(day.toordinal() + 7)
    # monthly: first day of the following month
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return date(year, month, 1)


# ---------------------------------------------------------------- validation
def _metrics(actual: np.ndarray, predicted: np.ndarray, baseline: np.ndarray) -> dict[str, float | None]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    err = predicted - actual
    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    bias = float(np.mean(err))
    denom = np.maximum(np.abs(actual), 1e-9)
    mape = float(np.mean(np.abs(err) / denom) * 100.0)
    ss_tot = float(np.sum((actual - actual.mean()) ** 2))
    r2 = float(1.0 - np.sum(err**2) / ss_tot) if ss_tot > 0 else None
    baseline_err = np.asarray(baseline, dtype=float) - actual
    mse_baseline = float(np.mean(baseline_err**2))
    skill = float(1.0 - np.mean(err**2) / mse_baseline) if mse_baseline > 0 else None
    return {"rmse": rmse, "mae": mae, "bias": bias, "mape": mape, "r2": r2, "skill_score": skill}


def _z_value(interval: float) -> float:
    return NormalDist().inv_cdf(0.5 + interval / 2.0)


def blocked_validation(
    series: Series,
    *,
    algorithm: str,
    horizon: int,
    n_folds: int,
    interval: float,
) -> AlgorithmScore:
    """Rolling-origin validation: train before the origin, test after it."""
    values, dates = series.values, series.dates
    n = len(values)
    test_size = max(horizon, 2)
    first_origin = n - n_folds * test_size
    if first_origin <= DEFAULT_LAGS + 5:
        raise UnprocessableError(
            f"series has {n} points; not enough history for {n_folds} blocked folds of {test_size} steps"
        )

    score = AlgorithmScore(algorithm=algorithm)
    pooled_residuals: list[float] = []
    for fold in range(n_folds):
        origin = first_origin + fold * test_size
        train_values = values[:origin]
        train_dates = dates[:origin]
        test_values = values[origin : origin + test_size]
        test_dates = dates[origin : origin + test_size]
        if len(test_values) == 0:
            continue

        X, y = _design_matrix(train_values, train_dates)
        estimator = _make_estimator(algorithm, len(y))
        estimator.fit(X, y)

        preds, _ = recursive_forecast(estimator, train_values, train_dates, len(test_values), series.cadence)
        pred_arr = np.asarray(preds, dtype=float)
        actual = np.asarray(test_values, dtype=float)
        baseline = np.full_like(actual, float(train_values[-1]))
        m = _metrics(actual, pred_arr, baseline)

        # Residual sigma from the one-step in-sample fit; intervals widen with
        # sqrt(lead), which is the standard random-walk uncertainty growth.
        in_sample = np.asarray(estimator.predict(X), dtype=float)
        residual = y - in_sample
        sigma = float(np.std(residual, ddof=1)) if len(residual) > 2 else float(np.std(residual))
        sigma = sigma if np.isfinite(sigma) and sigma > 0 else float(np.std(train_values) or 1e-6)
        sigma = max(sigma, 1e-9)
        pooled_residuals.extend(residual.tolist())

        z = _z_value(interval)
        leads = np.arange(1, len(pred_arr) + 1)
        half = z * sigma * np.sqrt(leads)
        lower = pred_arr - half
        upper = pred_arr + half
        coverage = float(np.mean((actual >= lower) & (actual <= upper)))

        score.folds.append(
            FoldResult(
                fold=fold,
                train_start=train_dates[0],
                train_end=train_dates[-1],
                test_start=test_dates[0],
                test_end=test_dates[-1],
                n_train=len(train_values),
                n_test=len(test_values),
                rmse=m["rmse"],
                mae=m["mae"],
                bias=m["bias"],
                mape=m["mape"],
                r2=m["r2"],
                skill_score=m["skill_score"],
                coverage=coverage,
            )
        )

    if not score.folds:
        raise UnprocessableError("blocked validation produced no folds")
    score.sigma = float(np.std(pooled_residuals, ddof=1)) if len(pooled_residuals) > 2 else 1e-6
    return score


def _required_points(horizon: int, n_folds: int, min_points: int) -> int:
    return max(min_points, DEFAULT_LAGS + 8 + (n_folds + 1) * max(horizon, 2))


# ------------------------------------------------------------------- persist
def _artifact_path(model_key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in model_key)[:120]
    directory = Path(settings.forecast_model_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{safe}.pkl"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _upsert_model(
    db: Session,
    *,
    series: Series,
    algorithm: str,
    score: AlgorithmScore,
    artifact_path: Path,
    params: dict[str, Any],
) -> MLModel:
    key = f"{algorithm}:{series.indicator_key}:{series.study_area_id}:v1"
    model = db.execute(select(MLModel).where(MLModel.key == key)).scalar_one_or_none()
    if model is None:
        model = MLModel(key=key, name=f"{algorithm} - {series.indicator_key}")
        db.add(model)
    aggregate = score.aggregate()
    model.algorithm = algorithm
    model.indicator_key = series.indicator_key
    model.study_area_id = series.study_area_id
    model.cadence = series.cadence
    model.n_lags = DEFAULT_LAGS
    model.feature_names_json = [
        *[f"lag_{i}" for i in range(1, DEFAULT_LAGS + 1)],
        *[f"rolling_{w}_{stat}" for w in ROLLING_WINDOWS for stat in ("mean", "std")],
        "doy_sin",
        "doy_cos",
        "trend_index",
    ]
    model.params_json = params
    model.train_start = series.dates[0]
    model.train_end = series.dates[-1]
    model.n_train = series.n
    model.metrics_json = aggregate
    model.rmse = aggregate["rmse"]
    model.mae = aggregate["mae"]
    model.bias = aggregate["bias"]
    model.skill_score = aggregate["skill_score"]
    model.artifact_path = str(artifact_path)
    model.artifact_sha256 = _sha256(artifact_path)
    model.is_active = True
    model.trained_at = utcnow()
    db.flush()
    # Only one active model per series: a newly selected algorithm retires the
    # previous winner instead of leaving several "active" models behind.
    for other in db.execute(
        select(MLModel).where(
            MLModel.indicator_key == series.indicator_key,
            MLModel.study_area_id == series.study_area_id,
            MLModel.id != model.id,
        )
    ).scalars():
        other.is_active = False
    return model


def _persist_evaluations(db: Session, *, model: MLModel, series: Series, score: AlgorithmScore, horizon: int) -> None:
    # Replace the previous generation's folds for this model row.
    for old in list(model.evaluations):
        db.delete(old)
    db.flush()
    for fold in score.folds:
        db.add(
            ModelEvaluation(
                model_id=model.id,
                indicator_key=series.indicator_key,
                study_area_id=series.study_area_id,
                fold=fold.fold,
                horizon_days=horizon,
                train_start=fold.train_start,
                train_end=fold.train_end,
                test_start=fold.test_start,
                test_end=fold.test_end,
                n_train=fold.n_train,
                n_test=fold.n_test,
                rmse=fold.rmse,
                mae=fold.mae,
                bias=fold.bias,
                mape=fold.mape,
                r2=fold.r2,
                skill_score=fold.skill_score,
                coverage=fold.coverage,
                metrics_json={
                    "rmse": fold.rmse,
                    "mae": fold.mae,
                    "bias": fold.bias,
                    "mape": fold.mape,
                    "r2": fold.r2,
                    "skill_score": fold.skill_score,
                    "coverage": fold.coverage,
                },
            )
        )
    db.flush()


# --------------------------------------------------------------------- public
def train_and_forecast(
    db: Session,
    *,
    study_area_id: int,
    indicator_key: str,
    actor: User | None = None,
    horizon: int | None = None,
    n_folds: int | None = None,
    algorithms: list[str] | None = None,
) -> dict[str, Any]:
    """Train, validate, select and issue a short-term forecast.

    Returns a summary dict.  A ``skipped`` result means the series was too
    short - no model and no forecast rows are written in that case.
    """
    area = db.get(StudyArea, study_area_id)
    if area is None:
        raise NotFoundError("Study area not found", details={"study_area_id": study_area_id})
    definition = db.execute(
        select(IndicatorDefinition).where(IndicatorDefinition.key == indicator_key)
    ).scalar_one_or_none()
    if definition is None:
        raise UnprocessableError(f"Unknown indicator '{indicator_key}'")

    horizon = horizon or settings.forecast_horizon_days
    n_folds = n_folds or settings.forecast_n_folds
    candidates = algorithms or available_algorithms()

    run = ForecastRun(
        study_area_id=study_area_id,
        indicator_key=indicator_key,
        horizon_days=horizon,
        status="running",
        issued_at=utcnow(),
    )
    db.add(run)
    db.flush()

    try:
        series = load_series(db, study_area_id=study_area_id, indicator_key=indicator_key)
    except NotFoundError as exc:
        run.status = "skipped"
        run.message = str(exc)
        run.finished_at = utcnow()
        db.flush()
        return _run_summary(run, skipped=True, reason=str(exc))

    required = _required_points(horizon, n_folds, settings.forecast_min_points)
    if series.n < required:
        run.status = "skipped"
        run.message = (
            f"insufficient history: {series.n} {series.cadence} points; "
            f"{required} required for {n_folds} blocked folds and a {horizon}-step horizon"
        )
        run.finished_at = utcnow()
        db.flush()
        return _run_summary(run, skipped=True, reason=run.message)

    scores: dict[str, AlgorithmScore] = {}
    failures: dict[str, str] = {}
    for algorithm in candidates:
        try:
            scores[algorithm] = blocked_validation(
                series,
                algorithm=algorithm,
                horizon=horizon,
                n_folds=n_folds,
                interval=settings.forecast_interval,
            )
        except Exception as exc:  # noqa: BLE001 - one algorithm must not kill the run
            failures[algorithm] = f"{type(exc).__name__}: {exc}"[:400]
            log.warning("Validation failed for %s/%s: %s", indicator_key, algorithm, exc)

    if not scores:
        run.status = "failed"
        run.message = "every candidate algorithm failed: " + "; ".join(f"{k}: {v}" for k, v in failures.items())
        run.finished_at = utcnow()
        db.flush()
        return _run_summary(run, skipped=False, reason=run.message)

    # Select on out-of-fold RMSE (MAE breaks ties).  This is model selection on
    # validation folds; the test windows were never used for fitting.
    ranked = sorted(
        scores.values(),
        key=lambda s: (
            s.aggregate()["rmse"] if s.aggregate()["rmse"] is not None else float("inf"),
            s.aggregate()["mae"] if s.aggregate()["mae"] is not None else float("inf"),
        ),
    )
    best = ranked[0]
    aggregate = best.aggregate()

    # Refit the winner on the full series and persist the artefact.
    X, y = _design_matrix(series.values, series.dates)
    estimator = _make_estimator(best.algorithm, len(y))
    estimator.fit(X, y)
    artifact = _artifact_path(f"{best.algorithm}:{indicator_key}:{study_area_id}:v1")
    with artifact.open("wb") as handle:
        pickle.dump(
            {
                "estimator": estimator,
                "algorithm": best.algorithm,
                "indicator_key": indicator_key,
                "study_area_id": study_area_id,
                "cadence": series.cadence,
                "sigma": best.sigma,
                "trained_at": utcnow().isoformat(),
            },
            handle,
        )

    model = _upsert_model(
        db,
        series=series,
        algorithm=best.algorithm,
        score=best,
        artifact_path=artifact,
        params={
            "candidates": candidates,
            "validation": "blocked rolling-origin",
            "n_folds": n_folds,
            "horizon": horizon,
            "interval": settings.forecast_interval,
            "sigma": best.sigma,
            "failures": failures,
        },
    )
    _persist_evaluations(db, model=model, series=series, score=best, horizon=horizon)

    preds, target_dates = recursive_forecast(estimator, series.values, series.dates, horizon, series.cadence)
    z = _z_value(settings.forecast_interval)
    issued = utcnow()

    # Replace this pair's previous machine-generated future values so repeated
    # daily runs do not accumulate duplicate target dates.  Manual forecasts
    # (source="manual") are never touched.
    from sqlalchemy import delete

    db.execute(
        delete(ForecastValue).where(
            ForecastValue.study_area_id == study_area_id,
            ForecastValue.indicator_key == indicator_key,
            ForecastValue.source == "model",
            ForecastValue.target_date >= target_dates[0],
        )
    )
    db.flush()

    rows: list[ForecastValue] = []
    for lead, (pred, target) in enumerate(zip(preds, target_dates), start=1):
        half = z * best.sigma * math.sqrt(lead)
        note = (
            f"Model: {best.algorithm} (v1, refit on {series.n} {series.cadence} observations "
            f"{series.dates[0]} to {series.dates[-1]}); blocked rolling-origin validation "
            f"({n_folds} folds), out-of-fold RMSE={aggregate['rmse']:.4g}, "
            f"MAE={aggregate['mae']:.4g}, bias={aggregate['bias']:.4g}, "
            f"skill vs persistence={aggregate['skill_score'] if aggregate['skill_score'] is not None else float('nan'):.4g}. "
            f"Interval is {int(settings.forecast_interval * 100)}% and widens with sqrt(lead)."
        )
        row = ForecastValue(
            study_area_id=study_area_id,
            indicator_key=indicator_key,
            target_date=target,
            value=float(pred),
            unit=series.unit,
            note=note,
            source="model",
            model_id=model.id,
            run_id=run.id,
            lead_time_days=lead,
            lower=float(pred - half),
            upper=float(pred + half),
            issued_at=issued,
            created_by_id=actor.id if actor else None,
        )
        db.add(row)
        rows.append(row)
    db.flush()

    run.model_id = model.id
    run.status = "succeeded"
    run.row_count = len(rows)
    run.finished_at = utcnow()
    run.metrics_json = {
        "algorithm": best.algorithm,
        "aggregate": aggregate,
        "candidates": {name: score.aggregate() for name, score in scores.items()},
        "failures": failures,
        "series": {
            "n": series.n,
            "cadence": series.cadence,
            "start": series.dates[0].isoformat(),
            "end": series.dates[-1].isoformat(),
        },
    }
    db.flush()

    audit_service.record(
        action="forecast.generate",
        resource_type="forecast_run",
        resource_id=run.id,
        actor=actor,
        db=db,
        message=(
            f"Generated {len(rows)} {indicator_key} forecasts for {area.name} "
            f"using {best.algorithm} (RMSE={aggregate['rmse']:.4g})"
        ),
        details={
            "study_area_id": study_area_id,
            "indicator_key": indicator_key,
            "algorithm": best.algorithm,
            "horizon": horizon,
            "model_id": model.id,
            "candidates": {k: v.aggregate() for k, v in scores.items()},
        },
    )
    return _run_summary(run, skipped=False, reason="")


def _run_summary(run: ForecastRun, *, skipped: bool, reason: str) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "status": run.status,
        "skipped": skipped,
        "reason": reason,
        "study_area_id": run.study_area_id,
        "indicator_key": run.indicator_key,
        "horizon_days": run.horizon_days,
        "row_count": run.row_count,
        "model_id": run.model_id,
        "metrics": run.metrics_json,
    }


def forecast_areas(db: Session) -> list[StudyArea]:
    """Study areas that actually have indicator data to forecast."""
    rows = db.execute(
        select(StudyArea).where(
            StudyArea.id.in_(select(IndicatorResult.study_area_id).where(IndicatorResult.value.is_not(None)).distinct())
        )
    ).scalars()
    return list(rows)


def run_forecasts(
    db: Session,
    *,
    study_area_ids: list[int] | None = None,
    indicator_keys: list[str] | None = None,
    actor: User | None = None,
    horizon: int | None = None,
) -> dict[str, Any]:
    """Run the engine over a set of areas/indicators and collect a summary.

    When ``indicator_keys`` is omitted the configured allowlist is intersected
    with the indicators that actually have results, so a daily run does not
    create empty "skipped" records for series that were never computed.
    """
    areas = db.execute(select(StudyArea)).scalars().all() if not study_area_ids else [
        a for a in (db.get(StudyArea, i) for i in study_area_ids) if a is not None
    ]
    requested = indicator_keys or list(settings.forecast_indicator_keys)
    results: list[dict[str, Any]] = []
    for area in areas:
        available = set(
            db.execute(
                select(IndicatorResult.indicator_key)
                .where(
                    IndicatorResult.study_area_id == area.id,
                    IndicatorResult.value.is_not(None),
                )
                .distinct()
            ).scalars()
        )
        keys = [k for k in requested if k in available]
        for key in keys:
            results.append(
                train_and_forecast(
                    db,
                    study_area_id=area.id,
                    indicator_key=key,
                    actor=actor,
                    horizon=horizon,
                )
            )
    return {
        "runs": results,
        "succeeded": sum(1 for r in results if r["status"] == "succeeded"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "rows": sum(r["row_count"] for r in results),
    }


@register_handler("forecast")
def handle_forecast_job(ctx: JobContext) -> dict:
    """Manual/queued forecast training run."""
    params = ctx.params
    indicator_key = params.get("indicator_key")
    study_area_id = params.get("study_area_id")
    horizon = int(params["horizon"]) if params.get("horizon") else None

    if indicator_key and study_area_id:
        result = train_and_forecast(
            ctx.db,
            study_area_id=int(study_area_id),
            indicator_key=str(indicator_key),
            actor=ctx.actor,
            horizon=horizon,
        )
        ctx.set_result(result)
        return result

    result = run_forecasts(
        ctx.db,
        study_area_ids=[int(i) for i in params.get("study_area_ids") or []] or None,
        indicator_keys=list(params.get("indicator_keys") or []) or None,
        actor=ctx.actor,
        horizon=horizon,
    )
    ctx.set_result(result)
    return result
