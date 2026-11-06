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


# --------------------------------------------------------------------- queue recovery & retries
def test_requeue_stale_running_jobs(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Jobs stranded in 'running' by a restart are picked up again."""
    stuck = _seed_job(kind="indicator", status="running", progress=30.0)
    real_pending = _seed_job(kind="indicator", status="pending")

    from app.services.jobs import requeue_stale_running

    with session_scope() as db:
        count = requeue_stale_running(db)
    assert count >= 1

    with session_scope() as db:
        assert db.get(Job, stuck).status == "pending"
        assert db.get(Job, stuck).message == "requeued after restart (previous run was interrupted)"
        assert db.get(Job, real_pending).status == "pending"

    # idempotent: no 'running' rows left
    with session_scope() as db:
        assert requeue_stale_running(db) == 0


def test_unprocessable_job_fails_without_retries(client: TestClient, admin_headers: dict[str, str]) -> None:
    """Deterministic input errors fail immediately instead of retrying 3x."""
    from app.services.jobs import execute_job_now, register_handler

    @register_handler("always-unprocessable-test")
    def _bad(ctx) -> dict:
        from app.core.errors import UnprocessableError

        raise UnprocessableError("this can never succeed")

    with session_scope() as db:
        job = Job(kind="always-unprocessable-test", status="pending", params_json={}, max_attempts=3)
        db.add(job)
        db.flush()
        execute_job_now(db, job.id)
        rid = job.id

    with session_scope() as db:
        row = db.get(Job, rid)
        assert row.status == "failed"
        assert row.attempts == 1  # no doomed retries
        assert "this can never succeed" in row.error
