"""Tests for the forecasting engine, the daily scheduler and the pipeline.

The forecasting tests seed a *real* synthetic indicator series into the test
database and then exercise the same training/validation path used in
production - no mocks of the estimator, no fixed outputs.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from app.core.database import session_scope
from app.models import (
    ForecastRun,
    ForecastValue,
    IndicatorDefinition,
    IndicatorResult,
    MLModel,
    ModelEvaluation,
    SchedulerRun,
    StudyArea,
)
from app.services import forecasting
from app.services.pipeline import indicator_keys_for, run_daily_pipeline
from app.services import scheduler as scheduler_service


def _seed_series(
    *,
    indicator_key: str = "water_extent",
    n: int = 60,
    start: date = date(2025, 1, 1),
    unit: str = "km2",
    seed: int = 7,
) -> int:
    """Insert a realistic daily series and return the study-area id."""
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    values = (
        500.0
        + 0.35 * t
        + 40.0 * np.sin(2 * np.pi * t / 30.0)
        + rng.normal(0.0, 3.0, n)
    )
    with session_scope() as db:
        area = db.query(StudyArea).order_by(StudyArea.id.asc()).first()
        assert area is not None
        definition = (
            db.query(IndicatorDefinition)
            .filter(IndicatorDefinition.key == indicator_key)
            .one()
        )
        # Other test modules may have seeded the same indicator in the shared
        # session database; start from a clean series so block counts are exact.
        db.query(IndicatorResult).filter(
            IndicatorResult.study_area_id == area.id,
            IndicatorResult.indicator_key == indicator_key,
        ).delete()
        for offset, value in enumerate(values):
            observed = start + timedelta(days=offset)
            db.add(
                IndicatorResult(
                    definition_id=definition.id,
                    indicator_key=indicator_key,
                    study_area_id=area.id,
                    value=float(value),
                    unit=unit,
                    observed_start=observed,
                    observed_end=observed,
                )
            )
        return area.id


def _clear(area_id: int, indicator_key: str) -> None:
    with session_scope() as db:
        db.query(ForecastValue).filter(
            ForecastValue.study_area_id == area_id,
            ForecastValue.indicator_key == indicator_key,
        ).delete()
        db.query(ModelEvaluation).filter(
            ModelEvaluation.indicator_key == indicator_key,
            ModelEvaluation.study_area_id == area_id,
        ).delete()
        db.query(ForecastRun).filter(
            ForecastRun.study_area_id == area_id,
            ForecastRun.indicator_key == indicator_key,
        ).delete()
        db.query(MLModel).filter(
            MLModel.indicator_key == indicator_key,
            MLModel.study_area_id == area_id,
        ).delete()
        db.query(IndicatorResult).filter(
            IndicatorResult.study_area_id == area_id,
            IndicatorResult.indicator_key == indicator_key,
        ).delete()


# --------------------------------------------------------------------- engine
def test_engine_trains_validates_and_issues_forecasts(client):
    area_id = _seed_series()
    try:
        with session_scope() as db:
            summary = forecasting.train_and_forecast(
                db,
                study_area_id=area_id,
                indicator_key="water_extent",
                horizon=5,
                n_folds=3,
            )
            db.commit()

        assert summary["status"] == "succeeded", summary
        assert summary["row_count"] == 5

        with session_scope() as db:
            model = db.query(MLModel).filter(MLModel.id == summary["model_id"]).one()
            assert model.algorithm in forecasting.available_algorithms()
            assert model.n_train == 60
            assert model.rmse is not None and model.rmse > 0
            assert model.mae is not None and model.mae > 0
            assert model.skill_score is not None
            assert model.artifact_path and model.artifact_sha256

            folds = (
                db.query(ModelEvaluation)
                .filter(ModelEvaluation.model_id == model.id)
                .order_by(ModelEvaluation.fold.asc())
                .all()
            )
            assert len(folds) == 3
            for fold in folds:
                assert fold.train_end < fold.test_start  # blocked, no leakage
                assert fold.n_train > 0 and fold.n_test > 0
                assert fold.rmse is not None and fold.rmse >= 0
                assert fold.coverage is not None and 0.0 <= fold.coverage <= 1.0

            rows = (
                db.query(ForecastValue)
                .filter(
                    ForecastValue.study_area_id == area_id,
                    ForecastValue.indicator_key == "water_extent",
                    ForecastValue.source == "model",
                )
                .order_by(ForecastValue.target_date.asc())
                .all()
            )
            assert len(rows) == 5
            for lead, row in enumerate(rows, start=1):
                assert row.lead_time_days == lead
                assert row.lower is not None and row.upper is not None
                assert row.lower < row.value < row.upper
                assert row.model_id == model.id
                assert "blocked rolling-origin" in row.note

            # Intervals widen with sqrt(lead): the last one is the widest.
            widths = [row.upper - row.lower for row in rows]
            assert widths[-1] > widths[0]

            run = db.query(ForecastRun).filter(ForecastRun.id == summary["run_id"]).one()
            assert run.status == "succeeded"
            assert run.metrics_json["algorithm"] == model.algorithm
            assert "candidates" in run.metrics_json
    finally:
        _clear(area_id, "water_extent")


def test_short_series_is_skipped_without_inventing_values(client):
    area_id = _seed_series(indicator_key="turbidity_proxy", n=10, unit="NDTI")
    try:
        with session_scope() as db:
            summary = forecasting.train_and_forecast(
                db,
                study_area_id=area_id,
                indicator_key="turbidity_proxy",
            )
            db.commit()

        assert summary["status"] == "skipped"
        assert summary["row_count"] == 0
        with session_scope() as db:
            assert (
                db.query(ForecastValue)
                .filter(
                    ForecastValue.study_area_id == area_id,
                    ForecastValue.indicator_key == "turbidity_proxy",
                )
                .count()
                == 0
            )
    finally:
        _clear(area_id, "turbidity_proxy")


def test_repeated_runs_replace_model_forecasts_without_duplicates(client):
    area_id = _seed_series(indicator_key="chlorophyll_a_proxy", unit="index")
    try:
        with session_scope() as db:
            first = forecasting.train_and_forecast(
                db, study_area_id=area_id, indicator_key="chlorophyll_a_proxy", horizon=4
            )
            db.commit()
        with session_scope() as db:
            second = forecasting.train_and_forecast(
                db, study_area_id=area_id, indicator_key="chlorophyll_a_proxy", horizon=4
            )
            db.commit()

        assert first["status"] == second["status"] == "succeeded"
        with session_scope() as db:
            rows = (
                db.query(ForecastValue)
                .filter(
                    ForecastValue.study_area_id == area_id,
                    ForecastValue.indicator_key == "chlorophyll_a_proxy",
                    ForecastValue.source == "model",
                )
                .all()
            )
            assert len(rows) == 4
            assert {row.run_id for row in rows} == {second["run_id"]}
    finally:
        _clear(area_id, "chlorophyll_a_proxy")


def test_forecast_api_exposes_models_and_fold_metrics(client, admin_headers):
    area_id = _seed_series(indicator_key="surface_water_temperature", unit="degC")
    try:
        with session_scope() as db:
            summary = forecasting.train_and_forecast(
                db,
                study_area_id=area_id,
                indicator_key="surface_water_temperature",
                horizon=3,
            )
            db.commit()

        response = client.get(
            "/api/v1/forecasts/models",
            params={"indicator_key": "surface_water_temperature"},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] >= 1
        assert payload["items"][0]["rmse"] is not None

        response = client.get(
            "/api/v1/forecasts/evaluations",
            params={"model_id": summary["model_id"]},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        folds = response.json()["items"]
        assert len(folds) >= 1
        assert all(fold["rmse"] is not None for fold in folds)

        response = client.get("/api/v1/forecasts/status", headers=admin_headers)
        assert response.status_code == 200, response.text
        status = response.json()
        assert status["enabled"] is True
        assert "ridge" in status["algorithms"]
        assert status["sklearn_available"] is True

        response = client.get(
            "/api/v1/disaster/forecasts",
            params={"indicator_key": "surface_water_temperature"},
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert items and items[0]["source"] == "model"
        assert items[0]["model_algorithm"] is not None
        assert items[0]["lower"] is not None
    finally:
        _clear(area_id, "surface_water_temperature")


# ------------------------------------------------------------------ scheduler
def test_scheduler_daily_run_is_idempotent(client):
    now = datetime(2031, 3, 4, 3, 0)
    with session_scope() as db:
        db.query(SchedulerRun).filter(SchedulerRun.run_date == now.date()).delete()
        db.commit()

    first = scheduler_service.start_daily_run(now=now, trigger="schedule")
    assert first["status"] == "queued"
    second = scheduler_service.start_daily_run(now=now, trigger="schedule")
    assert second["status"] == "skipped"
    assert second["run_id"] == first["run_id"]

    # A run that is still marked "running" is never doubled up, even by force.
    blocked = scheduler_service.start_daily_run(now=now, trigger="manual", force=True)
    assert blocked["status"] == "skipped"

    # Once the previous run has finished, a manual force re-runs the day.
    with session_scope() as db:
        run = db.query(SchedulerRun).filter(SchedulerRun.run_date == now.date()).one()
        run.status = "succeeded"
        db.commit()

    forced = scheduler_service.start_daily_run(now=now, trigger="manual", force=True)
    assert forced["status"] == "queued"
    assert forced["run_id"] == first["run_id"]

    with session_scope() as db:
        run = db.query(SchedulerRun).filter(SchedulerRun.run_date == now.date()).one()
        assert run.trigger == "manual"
        assert run.job_id == forced["job_id"]


def test_scheduler_status_and_timing(client):
    now = datetime(2031, 5, 1, 0, 0)
    assert scheduler_service.seconds_until_next(now) > 0
    with session_scope() as db:
        status = scheduler_service.status(db)
    assert status["scheduled_time_utc"].count(":") == 1
    assert status["scheduled_sources"] >= 0
    assert status["study_areas"] >= 1


def test_scheduler_api_returns_status(client, admin_headers):
    response = client.get("/api/v1/scheduler/status", headers=admin_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True
    assert "next_run_at" in body

    response = client.get("/api/v1/scheduler/runs", headers=admin_headers)
    assert response.status_code == 200, response.text


# ------------------------------------------------------------------- pipeline
def test_capability_mapping_covers_required_indicators():
    keys = indicator_keys_for({"optical", "thermal", "altimetry"})
    for required in (
        "chlorophyll_a_proxy",
        "turbidity_proxy",
        "surface_water_temperature",
        "water_extent",
        "water_level_altimetry",
    ):
        assert required in keys


def test_daily_pipeline_runs_with_no_scheduled_sources(client):
    with session_scope() as db:
        summary = run_daily_pipeline(
            db,
            run_date=date(2031, 6, 1),
            trigger="manual",
            source_ids=[-1],  # force an empty source list without touching config
        )
        db.commit()

    assert summary["run_date"] == "2031-06-01"
    assert summary["sources"] == []
    assert summary["forecasts"] is not None
    assert summary["alerts"]["dry_run"] is False
