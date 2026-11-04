"""Data source management: CRUD, filtering, connection test, and permissions."""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.core.enums import DATA_SOURCE_CATEGORIES


def _create_source(
    client: TestClient,
    headers: dict[str, str],
    *,
    name: str = "CHIRPS test source",
    provider_key: str = "chirps",
    category: str = "satellite_rainfall",
    is_enabled: bool = True,
) -> dict:
    response = client.post(
        "/api/v1/admin/data-sources",
        json={
            "name": name,
            "provider_key": provider_key,
            "category": category,
            "dataset_name": "CHIRPS v2.0 daily",
            "dataset_identifier": "chirps-v2-0",
            "description": "test data source",
            "is_enabled": is_enabled,
            "temporal_start": date(2020, 1, 1).isoformat(),
            "temporal_end": date(2026, 12, 31).isoformat(),
            "auth_method": "none",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------- CRUD
def test_create_list_get_update_delete_data_source(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    source = _create_source(client, admin_headers)
    assert source["name"] == "CHIRPS test source"
    assert source["provider_key"] == "chirps"
    assert source["is_enabled"] is True

    # list
    listed = client.get("/api/v1/admin/data-sources", headers=admin_headers).json()
    assert any(s["id"] == source["id"] for s in listed["items"])

    # get
    got = client.get(f"/api/v1/admin/data-sources/{source['id']}", headers=admin_headers).json()
    assert got["id"] == source["id"]
    assert got["category"] == "climate"

    # update
    updated = client.patch(
        f"/api/v1/admin/data-sources/{source['id']}",
        json={"description": "updated description", "is_enabled": False},
        headers=admin_headers,
    ).json()
    assert updated["description"] == "updated description"
    assert updated["is_enabled"] is False

    # delete
    deleted = client.delete(
        f"/api/v1/admin/data-sources/{source['id']}", headers=admin_headers
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/admin/data-sources/{source['id']}", headers=admin_headers).status_code == 404


def test_data_source_filtering(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    _create_source(client, admin_headers, name="CHIRPS rainfall", provider_key="chirps", category="satellite_rainfall")
    _create_source(client, admin_headers, name="Sentinel2 optical", provider_key="sentinel2_mpc", category="sentinel2")

    listed = client.get(
        "/api/v1/admin/data-sources",
        params={"category": "climate", "size": 50},
        headers=admin_headers,
    ).json()
    assert all(s["category"] == "climate" for s in listed["items"])
    assert len(listed["items"]) == 1

    listed = client.get(
        "/api/v1/admin/data-sources",
        params={"provider_key": "sentinel2_mpc", "size": 50},
        headers=admin_headers,
    ).json()
    assert all(s["provider_key"] == "sentinel2_mpc" for s in listed["items"])

    disabled = client.get(
        "/api/v1/admin/data-sources",
        params={"enabled": "false", "size": 50},
        headers=admin_headers,
    ).json()
    assert all(s["is_enabled"] is False for s in disabled["items"])


def test_data_source_validation(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    # bad category
    bad = client.post(
        "/api/v1/admin/data-sources",
        json={"name": "x", "provider_key": "chirps", "category": "not-a-category"},
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # bad provider key pattern
    bad = client.post(
        "/api/v1/admin/data-sources",
        json={"name": "x", "provider_key": "Chirps!", "category": "climate"},
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # temporal range inverted
    bad = client.post(
        "/api/v1/admin/data-sources",
        json={
            "name": "x",
            "provider_key": "chirps",
            "category": "climate",
            "temporal_start": "2026-12-01",
            "temporal_end": "2026-01-01",
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422


def test_data_source_test_connection(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    source = _create_source(client, admin_headers)
    response = client.post(
        f"/api/v1/admin/data-sources/{source['id']}/test", headers=admin_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_id"] == source["id"]
    assert body["status"] in {"verified", "failed"}
    assert "message" in body


# --------------------------------------------------------------------- permissions
def test_researcher_cannot_manage_data_sources(
    client: TestClient, admin_headers: dict[str, str], make_user
) -> None:
    _, headers = make_user("ds-researcher@example.org", role="researcher")
    assert client.get("/api/v1/admin/data-sources", headers=headers).status_code == 403
    assert client.post(
        "/api/v1/admin/data-sources",
        json={"name": "x", "provider_key": "chirps", "category": "climate"},
        headers=headers,
    ).status_code == 403


def test_categories_endpoint(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/providers/catalogue", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert {c["value"] for c in body["categories"]} == {k for k, _ in DATA_SOURCE_CATEGORIES}
    assert "auth_methods" in body
