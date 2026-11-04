"""Exports: creation, listing, retrieval and download gating."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_export_crud_and_list(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    response = client.post(
        "/api/v1/exports",
        json={
            "resource": "datasets",
            "format": "csv",
            "filters": {"study_area_id": default_study_area["id"]},
            "options": {},
        },
        headers=admin_headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["resource_type"] == "datasets"
    assert body["format"] == "csv"
    assert body["job_id"] is not None

    # list
    listed = client.get("/api/v1/exports", headers=admin_headers).json()
    assert listed["total"] >= 1
    assert any(e["id"] == body["id"] for e in listed["items"])

    # get
    got = client.get(f"/api/v1/exports/{body['id']}", headers=admin_headers).json()
    assert got["id"] == body["id"]

    # download before completion -> 422
    download = client.get(f"/api/v1/exports/{body['id']}/download", headers=admin_headers)
    assert download.status_code == 422


def test_export_validation(client: TestClient, admin_headers: dict[str, str]) -> None:
    # invalid resource
    bad = client.post(
        "/api/v1/exports",
        json={"resource": "not_a_resource", "format": "csv"},
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # invalid format
    bad = client.post(
        "/api/v1/exports",
        json={"resource": "datasets", "format": "xml"},
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # geotiff not allowed for datasets
    bad = client.post(
        "/api/v1/exports",
        json={"resource": "datasets", "format": "geotiff"},
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # raster requires geotiff/json
    bad = client.post(
        "/api/v1/exports",
        json={"resource": "raster", "format": "csv"},
        headers=admin_headers,
    )
    assert bad.status_code == 422


def test_export_unknown(client: TestClient, admin_headers: dict[str, str]) -> None:
    missing = client.get("/api/v1/exports/999999", headers=admin_headers)
    assert missing.status_code == 404
    download = client.get("/api/v1/exports/999999/download", headers=admin_headers)
    assert download.status_code == 404
