"""Audit log: listing, filtering, actions and resource types."""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient


# --------------------------------------------------------------------- listing & filters
def test_audit_list_and_filters(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    # generate some audit events by creating a study area and a user
    client.post(
        "/api/v1/study-areas",
        json={
            "name": "Audit probe area",
            "description": "",
            "boundary_geojson": {
                "type": "Polygon",
                "coordinates": [[[34.0, -12.0], [34.9, -12.0], [34.9, -12.9], [34.0, -12.9], [34.0, -12.0]]],
            },
        },
        headers=admin_headers,
    )

    listed = client.get("/api/v1/admin/audit", headers=admin_headers).json()
    assert listed["total"] >= 1
    assert "items" in listed
    first = listed["items"][0]
    for field in ("id", "created_at", "action", "resource_type", "outcome", "message"):
        assert field in first, first

    # action filter
    actions = client.get("/api/v1/admin/audit/actions", headers=admin_headers).json()
    assert "study_area.create" in actions

    # resource-type filter
    types = client.get("/api/v1/admin/audit/resource-types", headers=admin_headers).json()
    assert "study_area" in types

    # filter by resource type
    filtered = client.get(
        "/api/v1/admin/audit",
        params={"resource_type": "study_area", "size": 50},
        headers=admin_headers,
    ).json()
    assert all(r["resource_type"] == "study_area" for r in filtered["items"])

    # filter by action
    filtered = client.get(
        "/api/v1/admin/audit",
        params={"action": "study_area.create", "size": 50},
        headers=admin_headers,
    ).json()
    assert all(r["action"] == "study_area.create" for r in filtered["items"])

    # date range filter
    today = date.today().isoformat()
    filtered = client.get(
        "/api/v1/admin/audit",
        params={"date_from": today, "date_to": today, "size": 50},
        headers=admin_headers,
    ).json()
    assert all(r["created_at"].startswith(today) for r in filtered["items"])


# --------------------------------------------------------------------- permissions
def test_researcher_cannot_read_audit(
    client: TestClient, admin_headers: dict[str, str], make_user
) -> None:
    _, headers = make_user("audit-researcher@example.org", role="researcher")
    # researchers hold no admin.audit.read permission
    assert client.get("/api/v1/admin/audit", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/audit/actions", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/audit/resource-types", headers=headers).status_code == 403
