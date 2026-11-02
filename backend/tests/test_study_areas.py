"""Study area management: CRUD, validation, default protection and permissions."""
from __future__ import annotations

from fastapi.testclient import TestClient

AOI = {
    "type": "Polygon",
    "coordinates": [[[34.2, -12.7], [34.6, -12.7], [34.6, -12.3], [34.2, -12.3], [34.2, -12.7]]],
}


def _create_area(client: TestClient, headers: dict[str, str], *, name: str = "Test area") -> dict:
    response = client.post(
        "/api/v1/study-areas",
        json={"name": name, "description": "", "boundary_geojson": AOI},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------- CRUD
def test_study_area_crud(client: TestClient, admin_headers: dict[str, str]) -> None:
    area = _create_area(client, admin_headers)
    assert area["is_default"] is False
    assert area["minx"] == 34.2 and area["maxx"] == 34.6
    assert area["miny"] == -12.7 and area["maxy"] == -12.3

    listed = client.get("/api/v1/study-areas", headers=admin_headers).json()
    assert any(a["id"] == area["id"] for a in listed)

    got = client.get(f"/api/v1/study-areas/{area['id']}", headers=admin_headers).json()
    assert got["id"] == area["id"]
    assert got["name"] == "Test area"

    updated = client.patch(
        f"/api/v1/study-areas/{area['id']}",
        json={"name": "Renamed area", "description": "updated"},
        headers=headers,
    ).json()
    assert updated["name"] == "Renamed area"
    assert updated["description"] == "updated"

    deleted = client.delete(f"/api/v1/study-areas/{area['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/study-areas/{area['id']}", headers=headers).status_code == 404


def test_study_area_validation(client: TestClient, admin_headers: dict[str, str]) -> None:
    # duplicate name
    _create_area(client, admin_headers, name="Unique area")
    bad = client.post(
        "/api/v1/study-areas",
        json={"name": "Unique area", "description": "", "boundary_geojson": AOI},
        headers=admin_headers,
    )
    assert bad.status_code == 409

    # zero-area polygon
    bad = client.post(
        "/api/v1/study-areas",
        json={
            "name": "Zero area",
            "description": "",
            "boundary_geojson": {
                "type": "Polygon",
                "coordinates": [[[34.2, -12.7], [34.2, -12.7], [34.2, -12.7], [34.2, -12.7], [34.2, -12.7]]],
            },
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # invalid geometry type
    bad = client.post(
        "/api/v1/study-areas",
        json={
            "name": "Bad type",
            "description": "",
            "boundary_geojson": {"type": "Point", "coordinates": [34.2, -12.7]},
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # out of range coordinates
    bad = client.post(
        "/api/v1/study-areas",
        json={
            "name": "Out of range",
            "description": "",
            "boundary_geojson": {
                "type": "Polygon",
                "coordinates": [[[200.0, -12.7], [200.6, -12.7], [200.6, -12.3], [200.0, -12.3], [200.0, -12.7]]],
            },
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422


def test_default_study_area_cannot_be_deleted(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    area_id = default_study_area["id"]
    response = client.delete(f"/api/v1/study-areas/{area_id}", headers=admin_headers)
    assert response.status_code == 409


# --------------------------------------------------------------------- permissions
def test_researcher_can_read_but_not_write_study_areas(
    client: TestClient, admin_headers: dict[str, str], make_user
) -> None:
    _, headers = make_user("sa-researcher@example.org", role="researcher")
    assert client.get("/api/v1/study-areas", headers=headers).status_code == 200
    assert client.post(
        "/api/v1/study-areas",
        json={"name": "x", "description": "", "boundary_geojson": AOI},
        headers=headers,
    ).status_code == 403
