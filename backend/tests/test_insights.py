"""Live-signature endpoints: patterns + the four properties over HTTP."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_patterns_catalogue(client: TestClient, admin_headers: dict[str, str]) -> None:
    r = client.get("/api/v1/insights/patterns", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "water_extent" in body["strategies"]
    assert set(body["adapters"]) >= {"chirps", "nasa_power", "sentinel2"}


def test_strategy_index(client: TestClient, admin_headers: dict[str, str]) -> None:
    r = client.post(
        "/api/v1/insights/index",
        headers=admin_headers,
        json={
            "strategy_key": "water_extent",
            "bands": {"green": [[0.3, 0.4], [0.2, 0.5]], "swir1": [[0.1, 0.15], [0.2, 0.1]]},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["procedure"] == "MNDWI"
    assert body["unit"] == "1"
    assert body["value"] is not None


def test_validate_gauges_rmse(client: TestClient, admin_headers: dict[str, str]) -> None:
    r = client.post(
        "/api/v1/insights/validate-gauges",
        headers=admin_headers,
        json={
            "estimates": [{"lat": -12.5, "lon": 34.5, "value": 474.5}],
            "gauges": [{"lat": -12.48, "lon": 34.52, "elevation_m": 474.8}],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["unit"] == "m"
    assert body["rmse"] >= 0


def test_unit_check_catches_cm_vs_m(client: TestClient, admin_headers: dict[str, str]) -> None:
    r = client.post(
        "/api/v1/insights/unit-check",
        headers=admin_headers,
        json={"value": 1500, "unit": "cm", "expected_value": 1500, "expected_unit": "m"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["equal"] is False


def test_risk_matrix_confusion(client: TestClient, admin_headers: dict[str, str]) -> None:
    r = client.post(
        "/api/v1/insights/risk-matrix",
        headers=admin_headers,
        json={
            "indicators": [
                {"study_area": "A", "date": "2026-01-01", "value": 6100},
                {"study_area": "A", "date": "2026-01-02", "value": 3000},
            ],
            "events": [
                {"study_area": "A", "date": "2026-01-01", "outcome": "flood"},
                {"study_area": "A", "date": "2026-01-02", "outcome": "none"},
            ],
            "threshold": {"operator": "gt", "value_low": 5000},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tp"] == 1
    assert body["tn"] == 1
    assert body["accuracy"] == 1.0


def test_cloud_gap_flag(client: TestClient, admin_headers: dict[str, str]) -> None:
    r = client.post(
        "/api/v1/insights/cloud-gap",
        headers=admin_headers,
        json={
            "values": [[1, 1, 1], [1, 9, 1], [1, 1, 1]],
            "cloud_mask": [[False, False, False], [False, True, False], [False, False, False]],
            "date": "2026-01-01",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["quality_flag"] == "CLOUD_CONTAMINATED"
    assert body["is_observation"] is False
    assert body["gap_interpolated_count"] == 1
