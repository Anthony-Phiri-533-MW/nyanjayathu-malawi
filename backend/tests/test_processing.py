"""Processing: operations list, run creation and run inspection."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_processing_operations(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/processing/operations", headers=admin_headers)
    assert response.status_code == 200
    operations = response.json()
    assert len(operations) >= 1
    for op in operations:
        assert "key" in op


def test_processing_run_crud(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    # seed a dataset to process
    from app.core.database import session_scope
    from app.models import Dataset

    with session_scope() as db:
        dataset = Dataset(
            title="Processable dataset",
            provider_key="chirps",
            category="climate",
            product_type="demo",
            kind="observed",
            is_raw=True,
            study_area_id=default_study_area["id"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 7),
            quality_flag="UNVALIDATED",
            quality_reason="seeded",
        )
        db.add(dataset)
        db.flush()
        dataset_id = dataset.id

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
    assert body["input_dataset_ids"] == [dataset_id]
    assert body["job_id"] is not None

    # list runs
    listed = client.get("/api/v1/processing/runs", headers=admin_headers).json()
    assert listed["total"] >= 1

    # get run
    got = client.get(f"/api/v1/processing/runs/{body['id']}", headers=admin_headers).json()
    assert got["id"] == body["id"]

    # unknown run
    missing = client.get("/api/v1/processing/runs/999999", headers=admin_headers)
    assert missing.status_code == 404


def test_processing_unknown_operation(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    from app.core.database import session_scope
    from app.models import Dataset

    with session_scope() as db:
        dataset = Dataset(
            title="Processable dataset 2",
            provider_key="chirps",
            category="climate",
            product_type="demo",
            kind="observed",
            is_raw=True,
            study_area_id=default_study_area["id"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 7),
            quality_flag="UNVALIDATED",
            quality_reason="seeded",
        )
        db.add(dataset)
        db.flush()
        dataset_id = dataset.id

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


# --------------------------------------------------------------------- permissions
def test_processing_permissions(client: TestClient, admin_headers: dict[str, str], make_user) -> None:
    _, headers = make_user("proc-researcher@example.org", role="researcher")
    # researchers hold research.processing.run
    response = client.get("/api/v1/processing/operations", headers=headers)
    assert response.status_code == 200
