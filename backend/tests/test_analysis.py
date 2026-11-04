"""Analysis: time series and period comparison."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.core.database import session_scope
from app.models import IndicatorDefinition, IndicatorResult


def _seed_results(study_area_id: int) -> None:
    with session_scope() as db:
        definition = db.query(IndicatorDefinition).filter_by(key="water_extent").one()
        for offset, value in enumerate([6100.0, 6200.0, 6300.0]):
            day = date(2026, 10, 1) + timedelta(days=offset)
            db.add(
                IndicatorResult(
                    definition_id=definition.id,
                    indicator_key="water_extent",
                    study_area_id=study_area_id,
                    value=value,
                    unit=definition.unit,
                    observed_start=day,
                    observed_end=day,
                    quality_flag="VALID",
                    quality_reason="seeded",
                )
            )


# --------------------------------------------------------------------- timeseries
def test_timeseries(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    _seed_results(default_study_area["id"])
    response = client.get(
        "/api/v1/analysis/timeseries",
        params={
            "indicator_key": "water_extent",
            "study_area_id": default_study_area["id"],
            "start_date": date(2026, 10, 1).isoformat(),
            "end_date": date(2026, 10, 3).isoformat(),
            "aggregation": "raw",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["indicator_key"] == "water_extent"
    assert body["aggregation"] == "raw"
    assert len(body["points"]) == 3
    assert body["points"][0]["value"] == 6100.0
    assert body["points"][2]["value"] == 6300.0

    # monthly aggregation
    response = client.get(
        "/api/v1/analysis/timeseries",
        params={
            "indicator_key": "water_extent",
            "study_area_id": default_study_area["id"],
            "aggregation": "monthly",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200


def test_timeseries_validation(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    # missing indicator key
    bad = client.get(
        "/api/v1/analysis/timeseries",
        params={"study_area_id": default_study_area["id"]},
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # indicator key too short
    bad = client.get(
        "/api/v1/analysis/timeseries",
        params={"indicator_key": "ab", "study_area_id": default_study_area["id"]},
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # unknown indicator key still returns a (possibly empty) series - service handles it
    response = client.get(
        "/api/v1/analysis/timeseries",
        params={"indicator_key": "not_an_indicator", "study_area_id": default_study_area["id"]},
        headers=admin_headers,
    )
    assert response.status_code in (200, 422)


# --------------------------------------------------------------------- comparison
def test_compare_periods(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    _seed_results(default_study_area["id"])
    # seed a second set in a later period
    with session_scope() as db:
        definition = db.query(IndicatorDefinition).filter_by(key="water_extent").one()
        db.add(
            IndicatorResult(
                definition_id=definition.id,
                indicator_key="water_extent",
                study_area_id=default_study_area["id"],
                value=7000.0,
                unit=definition.unit,
                observed_start=date(2026, 11, 1),
                observed_end=date(2026, 11, 1),
                quality_flag="VALID",
                quality_reason="seeded",
            )
        )

    response = client.post(
        "/api/v1/analysis/compare",
        json={
            "study_area_id": default_study_area["id"],
            "indicator_keys": ["water_extent"],
            "period_a": {"start": "2026-10-01", "end": "2026-10-03"},
            "period_b": {"start": "2026-11-01", "end": "2026-11-01"},
            "aggregation": "mean",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["study_area_id"] == default_study_area["id"]
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["indicator_key"] == "water_extent"
    assert entry["a"]["value"] is not None
    assert entry["b"]["value"] == 7000.0
    assert entry["delta"] is not None

    # inverted period
    bad = client.post(
        "/api/v1/analysis/compare",
        json={
            "study_area_id": default_study_area["id"],
            "indicator_keys": ["water_extent"],
            "period_a": {"start": "2026-11-01", "end": "2026-10-01"},
            "period_b": {"start": "2026-10-01", "end": "2026-10-03"},
            "aggregation": "mean",
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # bad aggregation
    bad = client.post(
        "/api/v1/analysis/compare",
        json={
            "study_area_id": default_study_area["id"],
            "indicator_keys": ["water_extent"],
            "period_a": {"start": "2026-10-01", "end": "2026-10-03"},
            "period_b": {"start": "2026-11-01", "end": "2026-11-01"},
            "aggregation": "product",
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422
