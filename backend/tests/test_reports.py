"""Report Generation module: periodic/custom builds, summary snapshot,
file-store persistence, PDF/CSV download and permissions.

Precise aggregate assertions run against *custom* windows (explicit dates) so
results do not depend on where "today" falls in a calendar month.  The
periodic test asserts derivation and completion only.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from app.core.database import session_scope
from app.models import Alert, IndicatorDefinition, IndicatorResult, StudyArea
from app.services.jobs import execute_job_now


def _seed_observed_result(indicator_key: str, study_area_id: int, value: float, day_offset: int) -> None:
    """Insert an IndicatorResult dated ``today + day_offset``."""
    day = date.today() + timedelta(days=day_offset)
    with session_scope() as db:
        definition = db.query(IndicatorDefinition).filter_by(key=indicator_key).one()
        db.add(
            IndicatorResult(
                definition_id=definition.id,
                indicator_key=indicator_key,
                study_area_id=study_area_id,
                value=value,
                unit=definition.unit,
                observed_start=day,
                observed_end=day,
                quality_flag="VALID",
                quality_reason="seeded by report test",
            )
        )


def _seed_alert(study_area_id: int, *, kind: str = "flood", severity: str = "warning") -> None:
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
                kind=kind,
                severity=severity,
                status="open",
                message="seeded by report test",
                times_seen=1,
            )
        )


def _create_forecast(
    client: TestClient,
    headers: dict[str, str],
    *,
    study_area_id: int,
    value: float,
    day_offset: int = 0,
) -> dict:
    response = client.post(
        "/api/v1/disaster/forecasts",
        json={
            "indicator_key": "rainfall_summary",
            "study_area_id": study_area_id,
            "target_date": str(date.today() + timedelta(days=day_offset)),
            "value": value,
            "unit": "mm",
            "note": "source: report test scenario",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_report(client: TestClient, headers: dict[str, str], payload: dict) -> dict:
    response = client.post("/api/v1/reports", json=payload, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()


def _run_report_job(client: TestClient, admin_headers: dict[str, str], report_id: int) -> dict:
    """Execute the queued build job synchronously and return the report."""
    detail = client.get(f"/api/v1/reports/{report_id}", headers=admin_headers).json()
    job_id = detail.get("job_id")
    assert job_id is not None
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        execute_job_now(db, job_id)
    return client.get(f"/api/v1/reports/{report_id}", headers=admin_headers).json()


def test_periodic_monthly_report_builds(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    report = _create_report(
        client, admin_headers, {"kind": "periodic", "period_type": "monthly", "format": "csv"}
    )
    assert report["status"] == "queued"
    assert report["period_start"] == date.today().replace(day=1).isoformat()
    assert report["period_end"] == date.today().isoformat()
    finished = _run_report_job(client, admin_headers, report["id"])
    assert finished["status"] == "completed"
    assert finished["file_name"].endswith(".csv")
    assert finished["download_url"] == f"/api/v1/reports/{report['id']}/download"
    assert finished["completed_at"] is not None
    assert finished["job_status"] == "succeeded"


def test_custom_report_summary_snapshot_aggregates(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    sa = default_study_area["id"]
    _seed_observed_result("water_extent", sa, 6100.0, -2)
    _seed_observed_result("water_extent", sa, 6300.0, 0)
    _seed_observed_result("rainfall_summary", sa, 11.5, -1)
    _seed_alert(sa)
    _create_forecast(client, admin_headers, study_area_id=sa, value=23.4, day_offset=-1)

    # one NULL-valued result must be excluded from statistics, never zeroed
    day = date.today() - timedelta(days=3)
    with session_scope() as db:
        definition = db.query(IndicatorDefinition).filter_by(key="water_extent").one()
        db.add(
            IndicatorResult(
                definition_id=definition.id,
                indicator_key="water_extent",
                study_area_id=sa,
                value=None,
                unit=definition.unit,
                observed_start=day,
                observed_end=day,
                quality_flag="INSUFFICIENT_COVERAGE",
                quality_reason="seeded null",
            )
        )

    report = _create_report(
        client,
        admin_headers,
        {
            "kind": "custom",
            "period_start": str(date.today() - timedelta(days=3)),
            "period_end": str(date.today()),
            "format": "csv",
            "study_area_id": sa,
            "title": "Test aggregate snapshot",
        },
    )
    finished = _run_report_job(client, admin_headers, report["id"])
    assert finished["status"] == "completed"

    summary = client.get(f"/api/v1/reports/{report['id']}", headers=admin_headers).json()["summary_json"]
    indicators = {i["indicator_key"]: i for i in summary["indicators"]}
    water = indicators["water_extent"]
    assert water["result_count"] == 3
    assert water["computed_count"] == 2                     # NULL value excluded
    assert water["min_value"] == 6100.0 and water["max_value"] == 6300.0
    assert abs(water["mean_value"] - 6200.0) < 0.01
    assert water["first_value"] == 6100.0 and water["last_value"] == 6300.0
    assert water["direction"] == "increasing"
    assert indicators["rainfall_summary"]["direction"] == "single value"

    alerts = summary["alerts"]
    assert alerts["total"] >= 1
    assert alerts["by_kind"].get("flood", 0) >= 1
    assert alerts["highest_severity"] in ("warning", "critical")

    forecasts = summary["forecasts"]
    assert any(f["value"] == 23.4 and "report test scenario" in f["note"] for f in forecasts)

    overview = summary["overview"]
    assert overview["datasets_overlapping_period"] >= 0
    assert summary["study_area_focus"] == default_study_area["name"]


def test_pdf_report_download(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    report = _create_report(
        client,
        admin_headers,
        {
            "kind": "custom",
            "period_start": str(date.today() - timedelta(days=7)),
            "period_end": str(date.today()),
            "format": "pdf",
            "title": "Lake & Water <summary>",
            "note": "R&D <quality note>",
        },
    )
    finished = _run_report_job(client, admin_headers, report["id"])
    assert finished["status"] == "completed"
    assert finished["file_name"].endswith(".pdf")
    download = client.get(f"/api/v1/reports/{report['id']}/download", headers=admin_headers)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/pdf")
    assert download.content.startswith(b"%PDF-")
    assert download.headers["content-disposition"].endswith('.pdf"')


def test_csv_report_download_layout(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    report = _create_report(
        client,
        admin_headers,
        {
            "kind": "custom",
            "period_start": str(date.today() - timedelta(days=1)),
            "period_end": str(date.today()),
            "format": "csv",
            "include_sections": ["overview", "indicators", "forecasts", "alerts"],
        },
    )
    finished = _run_report_job(client, admin_headers, report["id"])
    assert finished["status"] == "completed"
    download = client.get(f"/api/v1/reports/{report['id']}/download", headers=admin_headers)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")
    text = (
        download.content.decode("utf-8-sig")
        if download.content[:3] == b"\xef\xbb\xbf"
        else download.content.decode("utf-8")
    )
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["section", "name", "metric", "value", "unit", "detail"]
    sections = {r[0] for r in rows[1:]}
    assert {"report", "overview", "indicators", "forecasts", "alerts"} <= sections
    # every row has the fixed column count
    assert all(len(r) == 6 for r in rows)


def test_indicator_statistics_respect_study_area_and_count_null_quality_flags(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    study_area_id = default_study_area["id"]
    start = date(2001, 1, 1)
    end = date(2001, 1, 2)
    with session_scope() as db:
        definition = db.query(IndicatorDefinition).filter_by(key="water_extent").one()
        area = db.get(StudyArea, study_area_id)
        assert area is not None
        other_area = StudyArea(
            name="Report statistics scope",
            description="",
            boundary_geojson=area.boundary_geojson,
            minx=area.minx,
            miny=area.miny,
            maxx=area.maxx,
            maxy=area.maxy,
        )
        db.add(other_area)
        db.flush()
        db.add_all(
            [
                IndicatorResult(
                    definition_id=definition.id,
                    indicator_key=definition.key,
                    study_area_id=study_area_id,
                    value=10.0,
                    unit=definition.unit,
                    observed_start=start,
                    observed_end=start,
                    quality_flag="VALID",
                ),
                IndicatorResult(
                    definition_id=definition.id,
                    indicator_key=definition.key,
                    study_area_id=study_area_id,
                    value=None,
                    unit=definition.unit,
                    observed_start=end,
                    observed_end=end,
                    quality_flag="INSUFFICIENT_COVERAGE",
                ),
                IndicatorResult(
                    definition_id=definition.id,
                    indicator_key=definition.key,
                    study_area_id=other_area.id,
                    value=1000.0,
                    unit=definition.unit,
                    observed_start=end,
                    observed_end=end,
                    quality_flag="VALID",
                ),
            ]
        )

    report = _create_report(
        client,
        admin_headers,
        {
            "kind": "custom",
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "format": "csv",
            "study_area_id": study_area_id,
            "indicator_keys": ["water_extent"],
            "include_sections": ["indicators"],
        },
    )
    finished = _run_report_job(client, admin_headers, report["id"])
    indicator = finished["summary_json"]["indicators"][0]

    assert indicator["result_count"] == 2
    assert indicator["computed_count"] == 1
    assert indicator["min_value"] == indicator["max_value"] == 10.0
    assert indicator["first_value"] == indicator["last_value"] == 10.0
    assert indicator["quality_flags"] == {"VALID": 1, "INSUFFICIENT_COVERAGE": 1}


def test_alerts_include_full_end_date_but_exclude_following_midnight(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    report_day = date(2001, 2, 1)
    with session_scope() as db:
        area = db.get(StudyArea, default_study_area["id"])
        assert area is not None
        scoped_area = StudyArea(
            name="Report alert window",
            description="",
            boundary_geojson=area.boundary_geojson,
            minx=area.minx,
            miny=area.miny,
            maxx=area.maxx,
            maxy=area.maxy,
        )
        db.add(scoped_area)
        db.flush()
        alerts = [
            Alert(
                study_area_id=scoped_area.id,
                indicator_key="water_extent",
                indicator_name="Water extent",
                metric_source="observed",
                metric_value=10.0,
                metric_date=report_day,
                unit="m",
                kind="flood",
                severity="warning",
                status="open",
                message="report window boundary",
                first_seen_at=datetime.combine(report_day, datetime.max.time()),
            ),
            Alert(
                study_area_id=scoped_area.id,
                indicator_key="water_extent",
                indicator_name="Water extent",
                metric_source="observed",
                metric_value=11.0,
                metric_date=report_day + timedelta(days=1),
                unit="m",
                kind="flood",
                severity="warning",
                status="open",
                message="following midnight",
                first_seen_at=datetime.combine(report_day + timedelta(days=1), datetime.min.time()),
            ),
        ]
        db.add_all(alerts)
        db.flush()
        expected_alert_id = alerts[0].id
        scoped_area_id = scoped_area.id

    report = _create_report(
        client,
        admin_headers,
        {
            "kind": "custom",
            "period_start": report_day.isoformat(),
            "period_end": report_day.isoformat(),
            "format": "csv",
            "study_area_id": scoped_area_id,
            "include_sections": ["alerts"],
        },
    )
    finished = _run_report_job(client, admin_headers, report["id"])
    summary = finished["summary_json"]["alerts"]

    assert summary["total"] == 1
    assert [alert["id"] for alert in summary["sample"]] == [expected_alert_id]


def test_indicator_filter_and_section_selection(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    _seed_observed_result("turbidity_proxy", default_study_area["id"], 18.0, -1)
    report = _create_report(
        client,
        admin_headers,
        {
            "kind": "custom",
            "period_start": str(date.today() - timedelta(days=2)),
            "period_end": str(date.today()),
            "format": "csv",
            "indicator_keys": ["turbidity_proxy"],
            "include_sections": ["indicators"],
        },
    )
    finished = _run_report_job(client, admin_headers, report["id"])
    summary = finished["summary_json"]
    assert "alerts" not in summary and "forecasts" not in summary and "overview" not in summary
    keys = [i["indicator_key"] for i in summary["indicators"]]
    assert keys == ["turbidity_proxy"]
    assert summary["indicators"][0]["is_proxy"] is True


def test_download_before_completion_rejected(client: TestClient, admin_headers: dict[str, str]) -> None:
    report = _create_report(
        client, admin_headers, {"kind": "periodic", "period_type": "weekly", "format": "pdf"}
    )
    response = client.get(f"/api/v1/reports/{report['id']}/download", headers=admin_headers)
    assert response.status_code == 422


def test_queued_report_can_be_canceled_and_retried(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    report = _create_report(
        client,
        admin_headers,
        {"kind": "periodic", "period_type": "weekly", "format": "csv"},
    )
    canceled = client.delete(f"/api/v1/reports/{report['id']}", headers=admin_headers)
    assert canceled.status_code == 204
    detail = client.get(f"/api/v1/reports/{report['id']}", headers=admin_headers).json()
    assert detail["status"] == "canceled"
    assert detail["job_status"] == "canceled"

    retried = client.post(f"/api/v1/reports/{report['id']}/retry", headers=admin_headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "queued"
    assert retried.json()["job_status"] == "pending"
    assert _run_report_job(client, admin_headers, report["id"])["status"] == "completed"


def test_validation_rules(client: TestClient, admin_headers: dict[str, str]) -> None:
    # periodic without period_type
    assert client.post("/api/v1/reports", json={"kind": "periodic"}, headers=admin_headers).status_code == 422
    # custom without explicit dates
    assert client.post("/api/v1/reports", json={"kind": "custom"}, headers=admin_headers).status_code == 422
    # end before start
    bad = client.post(
        "/api/v1/reports",
        json={
            "kind": "custom",
            "period_start": "2026-01-10",
            "period_end": "2026-01-01",
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422
    # unknown indicator key
    bad = client.post(
        "/api/v1/reports",
        json={
            "kind": "custom",
            "period_start": str(date.today()),
            "period_end": str(date.today()),
            "indicator_keys": ["not_an_indicator"],
        },
        headers=admin_headers,
    )
    assert bad.status_code == 422
    # unknown study area
    bad = client.post(
        "/api/v1/reports",
        json={
            "kind": "custom",
            "period_start": str(date.today()),
            "period_end": str(date.today()),
            "study_area_id": 999999,
        },
        headers=admin_headers,
    )
    assert bad.status_code == 404


def test_researcher_permissions(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict, make_user
) -> None:
    _, headers = make_user("report-researcher@example.org", role="researcher")
    listing = client.get("/api/v1/reports", headers=headers)
    assert listing.status_code == 200
    report = _create_report(
        client,
        headers,
        {"kind": "periodic", "period_type": "weekly", "format": "csv"},
    )
    assert report["created_by_email"] == "report-researcher@example.org"
    finished = _run_report_job(client, admin_headers, report["id"])
    assert finished["status"] == "completed"
    download = client.get(f"/api/v1/reports/{report['id']}/download", headers=headers)
    assert download.status_code == 200


def test_reports_are_listed_and_filterable(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    report = _create_report(
        client, admin_headers, {"kind": "periodic", "period_type": "daily", "format": "csv"}
    )
    listing = client.get("/api/v1/reports", params={"kind": "periodic", "size": 50}, headers=admin_headers).json()
    ids = [r["id"] for r in listing["items"]]
    assert report["id"] in ids
    by_status = client.get(
        "/api/v1/reports", params={"status": "completed", "size": 50}, headers=admin_headers
    ).json()
    assert all(r["status"] == "completed" for r in by_status["items"])
