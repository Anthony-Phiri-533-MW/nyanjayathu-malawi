"""Threshold management: CRUD, versioning, approval workflow and defaults."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _create_threshold(
    client: TestClient,
    headers: dict[str, str],
    *,
    indicator_key: str = "water_extent",
    operator: str = "gt",
    value_low: float = 5000.0,
    value_high: float | None = None,
    approval_status: str = "provisional",
    is_enabled: bool = True,
) -> dict:
    response = client.post(
        "/api/v1/admin/thresholds",
        json={
            "indicator_key": indicator_key,
            "indicator_name": "Water extent",
            "unit": "km²",
            "operator": operator,
            "value_low": value_low,
            "value_high": value_high,
            "approval_status": approval_status,
            "description": "test threshold",
            "is_enabled": is_enabled,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------- CRUD
def test_threshold_crud(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    threshold = _create_threshold(client, admin_headers)
    assert threshold["version"] == 1
    assert threshold["approval_status"] == "provisional"
    assert threshold["is_enabled"] is True

    # list
    listed = client.get("/api/v1/admin/thresholds", headers=admin_headers).json()
    assert any(t["id"] == threshold["id"] for t in listed["items"])

    # get
    got = client.get(f"/api/v1/admin/thresholds/{threshold['id']}", headers=admin_headers).json()
    assert got["id"] == threshold["id"]
    assert got["operator"] == "gt"

    # update (creates a new version)
    updated = client.patch(
        f"/api/v1/admin/thresholds/{threshold['id']}",
        json={"value_low": 6000.0, "change_note": "raised the bar"},
        headers=admin_headers,
    ).json()
    assert updated["value_low"] == 6000.0
    assert updated["version"] == 2  # version bumps on edit

    # delete
    deleted = client.delete(
        f"/api/v1/admin/thresholds/{threshold['id']}", headers=admin_headers
    )
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/admin/thresholds/{threshold['id']}", headers=admin_headers).status_code == 404


def test_threshold_version_history(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    threshold = _create_threshold(client, admin_headers, indicator_key="rainfall_summary")
    client.patch(
        f"/api/v1/admin/thresholds/{threshold['id']}",
        json={"value_low": 20.0, "change_note": "first revision"},
        headers=admin_headers,
    )
    client.patch(
        f"/api/v1/admin/thresholds/{threshold['id']}",
        json={"value_low": 30.0, "change_note": "second revision"},
        headers=admin_headers,
    )

    versions = client.get(
        f"/api/v1/admin/thresholds/{threshold['id']}/versions", headers=admin_headers
    ).json()
    assert len(versions) == 3  # initial + 2 revisions
    assert versions[0]["version"] == 1
    assert versions[1]["change_note"] == "first revision"
    assert versions[2]["change_note"] == "second revision"


def test_threshold_filtering(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    _create_threshold(client, admin_headers, indicator_key="water_extent", operator="gt", value_low=5000.0, approval_status="approved")
    _create_threshold(client, admin_headers, indicator_key="rainfall_summary", operator="lt", value_low=50.0, approval_status="provisional")

    listed = client.get(
        "/api/v1/admin/thresholds",
        params={"approval_status": "approved", "size": 50},
        headers=admin_headers,
    ).json()
    assert all(t["approval_status"] == "approved" for t in listed["items"])
    assert len(listed["items"]) == 1

    listed = client.get(
        "/api/v1/admin/thresholds",
        params={"operator": "lt", "size": 50},
        headers=admin_headers,
    ).json()
    assert all(t["operator"] == "lt" for t in listed["items"])


def test_threshold_validation(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    # bad operator
    bad = client.post(
        "/api/v1/admin/thresholds",
        json={
            "indicator_key": "water_extent",
            "indicator_name": "Water extent",
            "unit": "km²",
            "operator": "equals",
            "value_low": 5000.0,
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # between requires both bounds
    bad = client.post(
        "/api/v1/admin/thresholds",
        json={
            "indicator_key": "temperature_summary",
            "indicator_name": "Temperature summary",
            "unit": "°C",
            "operator": "between",
            "value_low": 10.0,
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # between low must be lower than high
    bad = client.post(
        "/api/v1/admin/thresholds",
        json={
            "indicator_key": "temperature_summary",
            "indicator_name": "Temperature summary",
            "unit": "°C",
            "operator": "between",
            "value_low": 40.0,
            "value_high": 10.0,
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # bad approval status
    bad = client.post(
        "/api/v1/admin/thresholds",
        json={
            "indicator_key": "water_extent",
            "indicator_name": "Water extent",
            "unit": "km²",
            "operator": "gt",
            "value_low": 5000.0,
            "approval_status": "final",
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422


# --------------------------------------------------------------------- permissions
def test_researcher_can_read_but_not_write_thresholds(
    client: TestClient, admin_headers: dict[str, str], make_user
) -> None:
    _, headers = make_user("thresh-researcher@example.org", role="researcher")
    assert client.get("/api/v1/admin/thresholds", headers=headers).status_code == 200
    assert client.post(
        "/api/v1/admin/thresholds",
        json={
            "indicator_key": "water_extent",
            "indicator_name": "Water extent",
            "unit": "km²",
            "operator": "gt",
            "value_low": 5000.0,
        },
        headers=headers,
    ).status_code == 403
