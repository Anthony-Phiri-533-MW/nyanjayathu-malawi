"""Processing: operations list, run creation and run inspection.

``JOBS_ENABLED`` is off in the suite, so the queued job is executed with the
documented synchronous helper (``execute_job_now``) — the same code path the
worker uses, minus threading.
"""
from __future__ import annotations

import json
from datetime import date

from fastapi.testclient import TestClient

from app.core.config import settings


def test_processing_operations(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/processing/operations", headers=admin_headers)
    assert response.status_code == 200
    operations = response.json()
    assert len(operations) >= 1
    for op in operations:
        assert "key" in op


def _seed_raster_dataset(study_area_id: int, title: str) -> int:
    """Create a real Sentinel-2-style dataset pointing at a small GeoTIFF."""
    import numpy as np

    from app.core.database import session_scope
    from app.models import Dataset
    from app.processing.io import write_geotiff
    from app.services.storage import relative
    from rasterio.transform import from_origin

    directory = settings.raw_dir / "processing_test"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{title.replace(' ', '_').lower()}.tif"

    # greens inside the AOI grid, SCL 4 (clear vegetation) except some cloud 8
    green = np.full((24, 24), 0.12, dtype="float32")
    scl = np.full((24, 24), 4, dtype="float32")
    scl[:6, :6] = 8  # genuine "cloudy" corner so the mask is not trivial
    transform = from_origin(34.3, -12.4, 0.01, 0.01)
    write_geotiff(path, np.stack([green, scl]), transform=transform, crs="EPSG:4326",
                  nodata=-9999.0, band_names=["green", "qa"])

    with session_scope() as db:
        dataset = Dataset(
            title=title,
            provider_key="sentinel2_mpc",
            category="satellite_optical",
            product_type="demo L2A scene",
            kind="observed",
            is_raw=True,
            study_area_id=study_area_id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 7),
            crs="EPSG:4326",
            resolution_m=10.0,
            format="geotiff",
            file_path=str(path),
            quality_flag="UNVALIDATED",
            quality_reason="seeded",
            metadata_json={
                "granules": [
                    {
                        "id": "synthetic-0",
                        "date": "2026-01-05",
                        # stored exactly like production ingestion does: a
                        # storage-relative POSIX path, not an absolute one
                        "path": relative(path),
                        "band_indexes": {"green": 1, "qa": 2},
                    }
                ],
                "bands": {
                    "green": {"crs": "EPSG:4326", "resolution_m": 10.0, "unit": "reflectance"},
                    "qa": {"crs": "EPSG:4326", "resolution_m": 10.0, "unit": "code"},
                },
                "capabilities": {"optical": True, "optical_qa": True},
            },
        )
        db.add(dataset)
        db.flush()
        return dataset.id


def test_processing_run_full_pipeline(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    from app.core.database import session_scope
    from app.services.jobs import execute_job_now

    dataset_id = _seed_raster_dataset(default_study_area["id"], "Processable dataset")

    response = client.post(
        "/api/v1/processing",
        json={
            "dataset_ids": [dataset_id],
            "operations": ["cloud_mask"],
            "params": {},
            "output_name": "test output",
        },
        headers=admin_headers,
        params={"study_area_id": default_study_area["id"]},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["operation"] == "cloud_mask"
    assert dataset_id in body["input_dataset_ids"]
    assert body["job_id"] is not None
    assert body["status"] == "pending"  # shell mirrors the queued job status

    # execute the queued job synchronously (same handler the worker runs)
    with session_scope() as db:
        execute_job_now(db, body["job_id"])

    # run rows now exist for the job
    listed = client.get(
        "/api/v1/processing/runs",
        params={"job_id": body["job_id"]},
        headers=admin_headers,
    )
    assert listed.status_code == 200, listed.text
    runs = listed.json()["items"]
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "succeeded"
    assert run["operation"] == "cloud_mask"
    assert run["input_dataset_ids"] == [dataset_id]

    # inspect a single run
    got = client.get(f"/api/v1/processing/runs/{run['id']}", headers=admin_headers)
    assert got.status_code == 200
    assert got.json()["id"] == run["id"]

    # unknown run
    missing = client.get("/api/v1/processing/runs/999999", headers=admin_headers)
    assert missing.status_code == 404

    # the run recorded its metrics and produced a product / derived dataset
    assert run["metrics"] is not None
    summary = (
        client.get("/api/v1/jobs", params={"size": 5}, headers=admin_headers)
    )
    assert summary.status_code == 200
    job_rows = [j for j in summary.json()["items"] if j["id"] == body["job_id"]]
    assert job_rows, "job row should exist"
    result = job_rows[0].get("result") or {}
    assert result.get("derived_dataset_id"), result


def test_processing_unknown_operation(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    dataset_id = _seed_raster_dataset(
        default_study_area["id"], "Processable dataset 2"
    )

    response = client.post(
        "/api/v1/processing",
        json={
            "dataset_ids": [dataset_id],
            "operations": ["not_a_real_operation"],
            "params": {},
        },
        headers=admin_headers,
    )
    assert response.status_code == 422


def test_processing_rejects_netcdf_points_dataset(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    """SRAL-style netCDF datasets are refused up front with an honest reason
    instead of a cryptic rasterio error retried to exhaustion."""
    from datetime import date as _date

    from app.core.database import session_scope
    from app.models import Dataset

    with session_scope() as db:
        dataset = Dataset(
            title="SRAL granule (netCDF points)",
            provider_key="sentinel3_sral",
            category="satellite_altimetry",
            product_type="SRAL L2 WAT",
            kind="observed",
            is_raw=True,
            study_area_id=default_study_area["id"],
            start_date=_date(2026, 10, 1),
            end_date=_date(2026, 10, 2),
            quality_flag="UNVALIDATED",
            quality_reason="seeded",
            metadata_json={
                "granules": [
                    {
                        "id": "S3A_SR_2_WAT_x",
                        "date": "2026-10-01",
                        "bands": {"standard-measurement": "raw/x/S3A_x_standard-measurement.nc"},
                    }
                ],
                "capabilities": ["altimetry"],
            },
        )
        db.add(dataset)
        db.flush()
        dataset_id = dataset.id

    response = client.post(
        "/api/v1/processing",
        json={
            "dataset_ids": [dataset_id],
            "operations": ["validate"],
            "params": {},
            "output_name": "should never run",
        },
        headers=admin_headers,
    )
    assert response.status_code == 422
    detail = response.json()["error"]
    assert "netCDF" in detail["message"] or "netCDF" in json.dumps(detail.get("details", {}))
    assert any("water_level_altimetry" in s for s in json.dumps(detail.get("details", {})).split()) \
        or "water_level_altimetry" in json.dumps(detail)


# --------------------------------------------------------------------- permissions
def test_processing_permissions(client: TestClient, admin_headers: dict[str, str], make_user) -> None:
    _, headers = make_user("proc-researcher@example.org", role="researcher")
    # researchers hold research.processing.run
    response = client.get("/api/v1/processing/operations", headers=headers)
    assert response.status_code == 200
