"""Jobs: listing, filtering, cancel and retry."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import session_scope
from app.models import Job


def _seed_job(
    *, kind: str = "ingestion", status: str = "succeeded", progress: float = 100.0
) -> int:
    with session_scope() as db:
        job = Job(
            kind=kind, status=status, progress=progress, message="done", params_json={}, attempts=1
        )
        db.add(job)
        db.flush()
        return job.id


# --------------------------------------------------------------------- listing & filters
def test_list_jobs_and_filters(client: TestClient, admin_headers: dict[str, str]) -> None:
    _seed_job(kind="ingestion", status="succeeded")
    _seed_job(kind="processing", status="failed")
    _seed_job(kind="report.build", status="pending")

    listed = client.get("/api/v1/jobs", headers=admin_headers).json()
    assert listed["total"] >= 3
    for job in listed["items"]:
        assert "kind" in job and "status" in job and "progress" in job

    # kind filter
    listed = client.get(
        "/api/v1/jobs", params={"kind": "ingestion", "size": 50}, headers=admin_headers
    ).json()
    assert all(j["kind"] == "ingestion" for j in listed["items"])

    # status filter
    listed = client.get(
        "/api/v1/jobs", params={"status": "failed", "size": 50}, headers=admin_headers
    ).json()
    assert all(j["status"] == "failed" for j in listed["items"])


def test_get_job(client: TestClient, admin_headers: dict[str, str]) -> None:
    job_id = _seed_job(kind="export", status="pending", progress=45.0)
    got = client.get(f"/api/v1/jobs/{job_id}", headers=admin_headers).json()
    assert got["id"] == job_id
    assert got["kind"] == "export"
    assert got["status"] == "pending"
    assert got["progress"] == 45.0

    missing = client.get("/api/v1/jobs/999999", headers=admin_headers)
    assert missing.status_code == 404
