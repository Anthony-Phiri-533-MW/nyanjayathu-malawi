"""Indicators: definitions, compute job and result browsing."""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient


def test_list_indicator_definitions(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/indicators/definitions", headers=admin_headers)
    assert response.status_code == 200
    definitions = response.json()
    assert len(definitions) >= 10
    keys = {d["key"] for d in definitions}
    expected = {
        "water_extent", "water_extent_change", "water_level_altimetry",
        "chlorophyll_a_proxy", "turbidity_proxy", "surface_water_temperature",
        "rainfall_summary", "rainfall_anomaly", "temperature_summary", "temperature_anomaly",
    }
    assert expected <= keys
    for d in definitions:
        for field in ("key", "name", "category", "description", "definition",
                      "unit", "method", "method_version", "is_proxy", "is_enabled"):
            assert field in d, d


def test_indicator_compute_job(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    response = client.post(
        "/api/v1/indicators/compute",
        json={
            "indicator_keys": ["water_extent"],
            "study_area_id": default_study_area["id"],
            "start_date": date(2026, 1, 1).isoformat(),
            "end_date": date(2026, 1, 7).isoformat(),
        },
        headers=admin_headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["kind"] == "indicator.compute"
    assert body["status"] in {"pending", "queued"}


def test_indicator_compute_validation(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    # no selection
    bad = client.post(
        "/api/v1/indicators/compute",
        json={"indicator_keys": ["water_extent"]},
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # unknown indicator key
    bad = client.post(
        "/api/v1/indicators/compute",
        json={
            "indicator_keys": ["not_an_indicator"],
            "study_area_id": default_study_area["id"],
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # inverted date range
    bad = client.post(
        "/api/v1/indicators/compute",
        json={
            "indicator_keys": ["water_extent"],
            "study_area_id": default_study_area["id"],
            "start_date": date(2026, 1, 10).isoformat(),
            "end_date": date(2026, 1, 1).isoformat(),
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422


def test_list_indicator_results(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    from app.core.database import session_scope
    from app.models import IndicatorDefinition, IndicatorResult

    with session_scope() as db:
        definition = db.query(IndicatorDefinition).filter_by(key="water_extent").one()
        db.add(
            IndicatorResult(
                definition_id=definition.id,
                indicator_key="water_extent",
                study_area_id=default_study_area["id"],
                value=6100.0,
                unit=definition.unit,
                observed_start=date(2026, 10, 1),
                observed_end=date(2026, 10, 1),
                quality_flag="VALID",
                quality_reason="seeded",
            )
        )

    listed = client.get(
        "/api/v1/indicators/results",
        params={"indicator_key": "water_extent", "size": 50},
        headers=admin_headers,
    ).json()
    assert listed["total"] >= 1
    assert any(r["indicator_key"] == "water_extent" for r in listed["items"])

    # quality flag filter
    listed = client.get(
        "/api/v1/indicators/results",
        params={"quality_flag": "VALID", "size": 50},
        headers=admin_headers,
    ).json()
    assert all(r["quality_flag"] == "VALID" for r in listed["items"])

    # get single result
    result_id = listed["items"][0]["id"]
    got = client.get(f"/api/v1/indicators/results/{result_id}", headers=admin_headers).json()
    assert got["id"] == result_id

    missing = client.get("/api/v1/indicators/results/999999", headers=admin_headers)
    assert missing.status_code == 404
