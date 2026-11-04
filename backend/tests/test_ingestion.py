"""Ingestion: job creation, validation and mocked adapter execution."""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient


class _FakeAdapter:
    """Stand-in provider adapter used to simulate discover/fetch outcomes."""

    key = "fake_provider"

    def __init__(self, client=None, config=None):
        self.client = client
        self.config = dict(config or {})

    def test_connection(self):
        from app.providers.base import TestResult
        return TestResult(ok=True, message="fake connection ok", latency_ms=5, details={})

    def discover(self, params):
        from app.providers.base import DiscoveredItem
        return [
            DiscoveredItem(
                asset_id="scene-001",
                title="Scene 001",
                start_date=params.start_date,
                end_date=params.end_date,
                bbox=params.bbox,
                media_type="image/tiff",
                assets={"blue": "https://example.com/scene-001-blue.tif"},
            )
        ]

    def fetch(self, params, item, progress=None):
        import tempfile
        from pathlib import Path

        from app.providers.base import FetchedArtifact
        dest = Path(params.dest_dir) if params.dest_dir else Path(tempfile.mkdtemp())
        dest.mkdir(parents=True, exist_ok=True)
        p = dest / "scene-001.tif"
        p.write_bytes(b"fake-raster-bytes")
        return FetchedArtifact(
            item=item,
            path=str(p),
            size_bytes=p.stat().st_size,
            checksum="abc123fakechecksum",
            variables=["blue"],
            metadata={"bands": {"blue": {"label": "Blue", "unit": "", "scale": 1.0, "offset": 0.0}},
                      "primary_variable": "blue",
                      "sample_point": [34.4, -12.5]},
        )


def _create_source(client, headers, *, provider_key: str = "chirps") -> dict:
    import uuid

    response = client.post(
        "/api/v1/admin/data-sources",
        json={
            "name": "Fake source",
            "provider_key": provider_key,
            "category": "satellite_rainfall",
            "dataset_name": "Fake dataset",
            "dataset_identifier": f"fake-{uuid.uuid4().hex[:8]}",
            "description": "",
            "is_enabled": True,
            "auth_method": "none",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------- mocked transport
def _install_fake_adapter(monkeypatch):
    import app.services.ingestion as ingestion_service

    monkeypatch.setattr(ingestion_service, "_adapter_for", lambda ds: _FakeAdapter())
    monkeypatch.setattr(ingestion_service, "sensor_for", lambda provider_key: "fake")


def test_ingestion_crud_and_run(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict, monkeypatch
) -> None:
    _install_fake_adapter(monkeypatch)
    sa = default_study_area["id"]
    source = _create_source(client, admin_headers)

    response = client.post(
        "/api/v1/ingestion",
        json={
            "data_source_id": source["id"],
            "study_area_id": sa,
            "start_date": date(2026, 1, 1).isoformat(),
            "end_date": date(2026, 1, 7).isoformat(),
            "variables": ["blue"],
        },
        headers=admin_headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["data_source_id"] == source["id"]
    assert body["study_area_id"] == sa
    assert body["job_id"] is not None

    # list
    listed = client.get("/api/v1/ingestion", headers=admin_headers).json()
    assert listed["total"] >= 1

    # get
    got = client.get(f"/api/v1/ingestion/{body['id']}", headers=admin_headers).json()
    assert got["id"] == body["id"]


def test_ingestion_validation(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    source = _create_source(client, admin_headers)
    sa = default_study_area["id"]

    # start after end
    bad = client.post(
        "/api/v1/admin/data-sources",
        json={"name": "x", "provider_key": "chirps", "category": "satellite_rainfall"},
        headers=admin_headers,
    )
    # reuse source id - actually just test range validation via a fresh source
    bad = client.post(
        "/api/v1/ingestion",
        json={
            "data_source_id": source["id"],
            "study_area_id": sa,
            "start_date": date(2026, 1, 10).isoformat(),
            "end_date": date(2026, 1, 1).isoformat(),
            "variables": [],
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422

    # unknown data source
    bad = client.post(
        "/api/v1/ingestion",
        json={
            "data_source_id": 999999,
            "study_area_id": sa,
            "start_date": date(2026, 1, 1).isoformat(),
            "end_date": date(2026, 1, 7).isoformat(),
            "variables": [],
        },
        headers=admin_headers,
    )
    assert bad.status_code == 404

    # disabled data source
    client.patch(
        f"/api/v1/admin/data-sources/{source['id']}",
        json={"is_enabled": False},
        headers=admin_headers,
    )
    bad = client.post(
        "/api/v1/ingestion",
        json={
            "data_source_id": source["id"],
            "study_area_id": sa,
            "start_date": date(2026, 1, 1).isoformat(),
            "end_date": date(2026, 1, 7).isoformat(),
            "variables": [],
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422


# --------------------------------------------------------------------- permissions
def test_researcher_ingestion_permissions(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict, make_user
) -> None:
    _, headers = make_user("ingest-researcher@example.org", role="researcher")
    source = _create_source(client, admin_headers)
    sa = default_study_area["id"]
    # researchers hold research.ingest.run so they can start ingestion
    response = client.post(
        "/api/v1/ingestion",
        json={
            "data_source_id": source["id"],
            "study_area_id": sa,
            "start_date": date(2026, 1, 1).isoformat(),
            "end_date": date(2026, 1, 7).isoformat(),
            "variables": [],
        },
        headers=headers,
    )
    assert response.status_code == 202, response.text
    # but cannot reach admin-only data-source writes
    assert client.get("/api/v1/admin/data-sources", headers=headers).status_code == 403
