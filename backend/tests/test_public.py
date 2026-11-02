"""Public Data module: anonymous read-only access, publish flags and privacy
guarantees.

Privacy rule under test: nothing is public until a staff member explicitly
publishes it, and unpublishing removes it from the public view immediately.
Public serializers must never leak storage internals or staff attribution.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.core.database import session_scope
from app.models import Alert, Dataset

NO_AUTH = {}  # explicit: the public dashboard needs no login


def _latest_id(model, *, study_area_id: int | None = None) -> int:
    with session_scope() as db:
        query = db.query(model)
        if study_area_id is not None:
            query = query.filter_by(study_area_id=study_area_id)
        return query.order_by(model.id.desc()).first().id


def _seed_dataset(*, title: str, study_area_id: int | None) -> None:
    with session_scope() as db:
        db.add(
            Dataset(
                title=title,
                provider_key="test_provider",
                category="satellite",
                product_type="demo",
                kind="observed",
                study_area_id=study_area_id,
                start_date=date.today() - timedelta(days=30),
                end_date=date.today(),
                quality_flag="UNVALIDATED",
                quality_reason="seeded by public test",
            )
        )


def _seed_alert(*, study_area_id: int | None, severity: str = "warning") -> None:
    with session_scope() as db:
        db.add(
            Alert(
                study_area_id=study_area_id,
                indicator_key="water_level_altimetry",
                indicator_name="Water level (altimetry)",
                metric_source="observed",
                metric_value=574.0,
                metric_date=date.today(),
                unit="m",
                kind="flood",
                severity=severity,
                status="open",
                message="seeded by public test",
                times_seen=1,
            )
        )


def _publish(
    client: TestClient,
    headers: dict[str, str],
    path: str,
    is_public: bool,
) -> dict:
    response = client.patch(path, json={"is_public": is_public}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_public_endpoints_need_no_login(client: TestClient) -> None:
    overview = client.get("/api/v1/public/overview", headers=NO_AUTH)
    datasets = client.get("/api/v1/public/datasets", headers=NO_AUTH)
    alerts = client.get("/api/v1/public/alerts", headers=NO_AUTH)
    geo = client.get("/api/v1/public/map", headers=NO_AUTH)
    for response in (overview, datasets, alerts, geo):
        assert response.status_code == 200, response.text
    body = overview.json()
    assert body["provenance"]
    assert body["dataset_count"] == 0  # nothing published yet


def test_only_public_data_is_exposed(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    sa = default_study_area["id"]
    _seed_dataset(title="Private dataset", study_area_id=sa)
    _seed_alert(study_area_id=sa)
    # ids are shared with other suites (session-scoped db) - resolve our rows
    dataset_id = _latest_id(Dataset)
    alert_id = _latest_id(Alert)

    # private by default: invisible everywhere
    assert client.get("/api/v1/public/datasets", headers=NO_AUTH).json()["total"] == 0
    assert client.get("/api/v1/public/alerts", headers=NO_AUTH).json()["total"] == 0
    features = client.get("/api/v1/public/map", headers=NO_AUTH).json()["features"]
    assert all(
        f["properties"]["id"] != sa for f in features
    )  # area itself stays private; other suites may have published one

    # publish both
    published = _publish(client, admin_headers, f"/api/v1/public/datasets/{dataset_id}", True)
    assert published["title"] == "Private dataset"
    published_alert = _publish(client, admin_headers, f"/api/v1/public/alerts/{alert_id}", True)
    assert published_alert["study_area_name"] is None  # area still private

    datasets = {
        d["id"]: d for d in client.get("/api/v1/public/datasets", headers=NO_AUTH).json()["items"]
    }
    assert datasets[dataset_id]["title"] == "Private dataset"
    alerts = {
        a["id"]: a for a in client.get("/api/v1/public/alerts", headers=NO_AUTH).json()["items"]
    }
    assert alerts[alert_id]["metric_value"] == 574.0

    overview = client.get("/api/v1/public/overview", headers=NO_AUTH).json()
    assert overview["dataset_count"] >= 1
    assert overview["alerts"]["total"] >= 1
    assert overview["alerts"]["by_kind"].get("flood", 0) >= 1
    assert overview["coverage_start"] is not None

    # unpublish hides again
    _publish(client, admin_headers, f"/api/v1/public/datasets/{dataset_id}", False)
    again = {
        d["id"]: d for d in client.get("/api/v1/public/datasets", headers=NO_AUTH).json()["items"]
    }
    assert dataset_id not in again


def test_public_dataset_never_leaks_internals(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    _seed_dataset(title="Leak check", study_area_id=default_study_area["id"])
    newest = client.get(
        "/api/v1/datasets", params={"size": 1}, headers=admin_headers
    ).json()["items"][0]
    dataset_id = newest["id"]
    _publish(client, admin_headers, f"/api/v1/public/datasets/{dataset_id}", True)
    record = client.get("/api/v1/public/datasets", headers=NO_AUTH).json()["items"][0]
    assert record["title"] == "Leak check"
    for forbidden in ("file_path", "checksum", "provenance_json", "metadata_json",
                      "created_by", "created_by_id", "data_source_id", "bands_json"):
        assert forbidden not in record
    assert record["quality_flag"] == "UNVALIDATED"


def test_publish_study_area_and_map(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    # dedicated area so this test does not depend on earlier publications
    created = client.post(
        "/api/v1/study-areas",
        json={
            "name": "Public map probe",
            "description": "temporary area for the public map test",
            "boundary_geojson": {
                "type": "Polygon",
                "coordinates": [[[34.0, -12.0], [34.9, -12.0], [34.9, -12.9], [34.0, -12.9], [34.0, -12.0]]],
            },
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    area = created.json()
    area_id = area["id"]

    _seed_dataset(title="Area dataset", study_area_id=area_id)
    _seed_alert(study_area_id=area_id)
    _seed_alert(study_area_id=area_id, severity="critical")

    result = _publish(client, admin_headers, f"/api/v1/public/study-areas/{area_id}", True)
    assert result["type"] == "FeatureCollection"
    features = result["features"]
    assert len(features) == 1
    props = features[0]["properties"]
    assert props["name"] == "Public map probe"
    assert props["public_dataset_count"] == 0           # dataset not yet published
    assert props["active_public_alerts"] == 0           # alerts not published either

    # resolve the ids of rows seeded on this fresh area
    dataset_id = _latest_id(Dataset, study_area_id=area_id)
    alert_ids = []
    with session_scope() as db:
        alert_ids = [
            a.id
            for a in db.query(Alert)
            .filter_by(study_area_id=area_id)
            .order_by(Alert.id.asc())
            .all()
        ]
    assert len(alert_ids) == 2

    _publish(client, admin_headers, f"/api/v1/public/datasets/{dataset_id}", True)
    for alert_id in alert_ids:
        _publish(client, admin_headers, f"/api/v1/public/alerts/{alert_id}", True)

    geo = client.get("/api/v1/public/map", headers=NO_AUTH).json()
    props = next(f["properties"] for f in geo["features"] if f["properties"]["id"] == area_id)
    assert props["public_dataset_count"] == 1
    assert props["active_public_alerts"] == 2
    assert props["highest_active_severity"] == "critical"

    # area name is now public, so published records may carry it
    alert = client.get("/api/v1/public/alerts", headers=NO_AUTH).json()["items"][0]
    assert alert["study_area_name"] == "Public map probe"

    # unpublish the area: map empties and names are hidden again
    _publish(client, admin_headers, f"/api/v1/public/study-areas/{area_id}", False)
    geo = client.get("/api/v1/public/map", headers=NO_AUTH).json()
    assert all(f["properties"]["id"] != area_id for f in geo["features"])
    alert = client.get("/api/v1/public/alerts", headers=NO_AUTH).json()["items"][0]
    if alert["study_area_id"] == area_id:
        assert alert["study_area_name"] is None


def test_public_alert_filters(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    # a kind no other test publishes, so filtering stays deterministic even in
    # the session-scoped database
    with session_scope() as db:
        db.add(
            Alert(
                study_area_id=default_study_area["id"],
                indicator_key="turbidity_proxy",
                indicator_name="Turbidity (proxy)",
                metric_source="observed",
                metric_value=92.0,
                metric_date=date.today(),
                unit="NTU",
                kind="water_quality",
                severity="warning",
                status="open",
                message="seeded by public test (water quality)",
                times_seen=1,
            )
        )
    newest_id = _latest_id(Alert)
    _publish(client, admin_headers, f"/api/v1/public/alerts/{newest_id}", True)

    exact = client.get(
        "/api/v1/public/alerts",
        params={"kind": "water_quality", "status": "open", "severity": "warning"},
        headers=NO_AUTH,
    ).json()
    assert exact["total"] == 1
    assert exact["items"][0]["id"] == newest_id
    assert exact["items"][0]["indicator_key"] == "turbidity_proxy"
    assert exact["items"][0]["unit"] == "NTU"

    resolved = client.get(
        "/api/v1/public/alerts",
        params={"kind": "water_quality", "status": "resolved"},
        headers=NO_AUTH,
    ).json()
    assert resolved["total"] == 0
    impossible = client.get(
        "/api/v1/public/alerts",
        params={"kind": "water_quality", "severity": "critical"},
        headers=NO_AUTH,
    ).json()
    assert impossible["total"] == 0


def test_publish_requires_permission(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict, make_user
) -> None:
    _seed_dataset(title="Guarded", study_area_id=default_study_area["id"])

    # researcher holds reports/disaster permissions but not public.publish
    _, researcher_headers = make_user("public-researcher@example.org", role="researcher")
    denied = client.patch(
        "/api/v1/public/datasets/1", json={"is_public": True}, headers=researcher_headers
    )
    assert denied.status_code == 403

    # anonymous walkers cannot toggle either
    anonymous = client.patch("/api/v1/public/datasets/1", json={"is_public": True})
    assert anonymous.status_code in (401, 403)

    # auditing captured the staff decision only (publish then check)
    _publish(client, admin_headers, "/api/v1/public/datasets/1", True)
    audit = client.get(
        "/api/v1/admin/audit", params={"resource_type": "dataset", "size": 10},
        headers=admin_headers,
    ).json()
    actions = [item["action"] for item in audit["items"]]
    assert "dataset.publish" in actions
