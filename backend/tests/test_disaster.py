"""Disaster Management module: evaluation engine, alert workflow, responses,
forecast records and permissions.

Evaluation inputs are engineered deterministically:
- forecast values are created through the API,
- "observed" metrics are seeded indicator results inserted directly into the
  session database (no ingestion needed to test the comparison logic).
Each test uses a distinct indicator key so thresholds cannot interfere.
"""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.core.database import session_scope
from app.models import IndicatorDefinition, IndicatorResult


def _create_threshold(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    indicator_key: str,
    indicator_name: str,
    operator: str,
    value_low: float,
    value_high: float | None = None,
    unit: str = "mm",
    approval_status: str = "approved",
) -> dict:
    response = client.post(
        "/api/v1/admin/thresholds",
        json={
            "indicator_key": indicator_key,
            "indicator_name": indicator_name,
            "unit": unit,
            "operator": operator,
            "value_low": value_low,
            "value_high": value_high,
            "approval_status": approval_status,
            "description": "test threshold",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_forecast(
    client: TestClient,
    headers: dict[str, str],
    *,
    study_area_id: int,
    indicator_key: str,
    value: float,
    target_date: str = "2026-11-01",
    unit: str = "mm",
    note: str = "source: illustrative forecast entered by test",
) -> dict:
    response = client.post(
        "/api/v1/disaster/forecasts",
        json={
            "indicator_key": indicator_key,
            "study_area_id": study_area_id,
            "target_date": target_date,
            "value": value,
            "unit": unit,
            "note": note,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _evaluate(client: TestClient, headers: dict[str, str], *, include_provisional: bool = False, dry_run: bool = False) -> dict:
    response = client.post(
        "/api/v1/disaster/evaluate",
        json={"include_provisional": include_provisional, "dry_run": dry_run},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_observed_result(indicator_key: str, study_area_id: int, value: float) -> None:
    """Insert an IndicatorResult row directly (no ingestion required)."""
    with session_scope() as db:
        definition = db.query(IndicatorDefinition).filter_by(key=indicator_key).one()
        db.add(
            IndicatorResult(
                definition_id=definition.id,
                indicator_key=indicator_key,
                study_area_id=study_area_id,
                value=value,
                unit=definition.unit,
                observed_start=date(2026, 10, 1),
                observed_end=date(2026, 10, 1),
                quality_flag="VALID",
                quality_reason="seeded by test",
            )
        )


def _match(out: dict, indicator_key: str, threshold_id: int | None = None, *, breached: bool | None = True) -> dict:
    """Pick this test's own match, never another test's threshold breach."""
    candidates = [
        m for m in out["matches"]
        if m["indicator_key"] == indicator_key
        and (threshold_id is None or m["threshold_id"] == threshold_id)
    ]
    assert candidates, f"no match found for {indicator_key}"
    match_next = next((m for m in candidates if breached is None or m["breached"] == breached), None)
    return match_next if match_next is not None else candidates[0]


def _alert_for(client: TestClient, headers: dict[str, str], indicator_key: str) -> list[dict]:
    response = client.get(
        "/api/v1/disaster/alerts", params={"indicator_key": indicator_key, "size": 100},
        headers=headers,
    )
    assert response.status_code == 200
    return response.json()["items"]


# ---------------------------------------------------------------- basics
def test_evaluate_with_no_approved_thresholds(client: TestClient, admin_headers: dict[str, str]) -> None:
    # Fresh DB: bootstrap thresholds are provisional, so the default run must
    # find nothing to evaluate (rather than acting on provisional values).
    out = _evaluate(client, admin_headers)
    assert out["thresholds_used"] == 0
    assert out["alerts_created"] == 0
    assert out["breached"] == 0


def test_provisional_thresholds_only_used_when_requested(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    # seed a provisional threshold (bootstrap seeds some; create one we control)
    sa = default_study_area["id"]
    _create_threshold(
        client, admin_headers,
        indicator_key="surface_water_temperature",
        indicator_name="Surface water temperature",
        operator="gt", value_low=40.0, unit="°C", approval_status="provisional",
    )
    _seed_observed_result("surface_water_temperature", sa, 44.0)

    # default: provisional ignored
    out = _evaluate(client, admin_headers)
    assert all(m["indicator_key"] != "surface_water_temperature" for m in out["matches"])

    # explicitly requested: evaluated and *labelled provisional*
    out = _evaluate(client, admin_headers, include_provisional=True)
    match = next(
        m for m in out["matches"]
        if m["indicator_key"] == "surface_water_temperature" and m["metric_value"] == 44.0
    )
    assert match["breached"] is True
    assert match["metric_source"] == "observed"
    alert = client.get(f"/api/v1/disaster/alerts/{match['alert_id']}", headers=admin_headers).json()
    assert "provisional" in alert["message"]


def test_dry_run_creates_no_alerts(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    sa = default_study_area["id"]
    _create_threshold(
        client, admin_headers,
        indicator_key="water_extent_change",
        indicator_name="Water extent change",
        operator="gt", value_low=100.0, unit="km²", approval_status="approved",
    )
    _create_forecast(
        client, admin_headers, study_area_id=sa,
        indicator_key="water_extent_change", value=150.0, unit="km²",
    )
    out = _evaluate(client, admin_headers, dry_run=True)
    assert out["dry_run"] is True
    assert out["breached"] == 1
    assert out["alerts_created"] == 0
    listed = client.get("/api/v1/disaster/alerts", headers=admin_headers).json()
    assert all(a["indicator_key"] != "water_extent_change" for a in listed["items"])


# ---------------------------------------------------------------- breaches
def test_forecast_breach_creates_drought_alert(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    sa = default_study_area["id"]
    _create_threshold(
        client, admin_headers,
        indicator_key="rainfall_summary",
        indicator_name="Rainfall summary",
        operator="lt", value_low=50.0, unit="mm", approval_status="approved",
    )
    forecast = _create_forecast(
        client, admin_headers, study_area_id=sa,
        indicator_key="rainfall_summary", value=12.5, unit="mm",
    )
    out = _evaluate(client, admin_headers)
    # scope to this indicator: other tests' thresholds may also breach in this run
    match = next(
        m for m in out["matches"]
        if m["indicator_key"] == "rainfall_summary" and m["breached"]
    )
    assert match["metric_source"] == "forecast"
    assert match["metric_value"] == 12.5
    assert match["metric_date"] == date(2026, 11, 1).isoformat()
    alerts = _alert_for(client, admin_headers, "rainfall_summary")
    assert len(alerts) == 1 and alerts[0]["id"] == match["alert_id"]
    alert = client.get(f"/api/v1/disaster/alerts/{match['alert_id']}", headers=admin_headers).json()
    assert alert["kind"] == "drought"
    assert alert["status"] == "open"
    assert alert["metric_source"] == "forecast"
    assert alert["unit"] == "mm"
    # the provenance note must travel with the record
    forecast_detail = client.get(
        "/api/v1/disaster/forecasts", params={"indicator_key": "rainfall_summary"},
        headers=admin_headers,
    ).json()
    assert any(f["id"] == forecast["id"] and f["note"] for f in forecast_detail["items"])


def test_severity_escalates_with_exceedance(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    sa = default_study_area["id"]
    _create_threshold(
        client, admin_headers,
        indicator_key="chlorophyll_a_proxy",
        indicator_name="Chlorophyll-a proxy",
        operator="gt", value_low=10.0, unit="µg/L", approval_status="approved",
    )
    # modest exceedance -> warning (10% over)
    _create_forecast(client, admin_headers, study_area_id=sa, indicator_key="chlorophyll_a_proxy", value=11.0, unit="µg/L")
    out = _evaluate(client, admin_headers)
    match = next(m for m in out["matches"] if m["indicator_key"] == "chlorophyll_a_proxy" and m["breached"])
    assert match["severity"] == "warning"
    alert = client.get(f"/api/v1/disaster/alerts/{match['alert_id']}", headers=admin_headers).json()
    assert alert["kind"] == "water_quality"
    alert_id = alert["id"]

    # large exceedance -> critical (30% over)
    _create_forecast(client, admin_headers, study_area_id=sa, indicator_key="chlorophyll_a_proxy", value=13.0, unit="µg/L")
    out = _evaluate(client, admin_headers)
    match = next(m for m in out["matches"] if m["indicator_key"] == "chlorophyll_a_proxy" and m["breached"])
    assert match["severity"] == "critical"
    alert = client.get(f"/api/v1/disaster/alerts/{alert_id}", headers=admin_headers).json()
    assert alert["severity"] == "critical"          # escalated, not duplicated
    assert alert["times_seen"] == 2
    assert any(r["response_type"] == "note" and "Re-evaluated" in r["note"] for r in alert["responses"])


def test_no_breach_creates_no_alert(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    sa = default_study_area["id"]
    _create_threshold(
        client, admin_headers,
        indicator_key="temperature_summary",
        indicator_name="Temperature summary",
        operator="between", value_low=-5.0, value_high=45.0, unit="°C", approval_status="approved",
    )
    _create_forecast(client, admin_headers, study_area_id=sa, indicator_key="temperature_summary", value=20.0, unit="°C")
    out = _evaluate(client, admin_headers)
    match = _match(out, "temperature_summary", breached=False)
    assert match["breached"] is False
    assert match["alert_id"] is None
    # other tests' thresholds may breach in the same run - irrelevant here
    assert not _alert_for(client, admin_headers, "temperature_summary")


def test_observed_indicator_result_triggers_alert(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    sa = default_study_area["id"]
    _create_threshold(
        client, admin_headers,
        indicator_key="water_extent",
        indicator_name="Water extent",
        operator="gt", value_low=5000.0, unit="km²", approval_status="approved",
    )
    _seed_observed_result("water_extent", sa, 6100.0)
    out = _evaluate(client, admin_headers)
    match = next(m for m in out["matches"] if m["indicator_key"] == "water_extent" and m["breached"])
    assert match["metric_source"] == "observed"
    assert match["metric_date"] == date(2026, 10, 1).isoformat()
    assert match["severity"] == "warning"   # 6100 vs 5000 => 22% exceedance
    alert = client.get(f"/api/v1/disaster/alerts/{match['alert_id']}", headers=admin_headers).json()
    assert alert["kind"] == "flood"
    assert alert["threshold_snapshot"]["operator"] == "gt"
    assert alert["threshold_snapshot"]["value_low"] == 5000.0


def test_missing_metric_is_skipped_not_invented(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    _create_threshold(
        client, admin_headers,
        indicator_key="turbidity_proxy",
        indicator_name="Turbidity proxy",
        operator="gt", value_low=100.0, unit="NTU", approval_status="approved",
    )
    out = _evaluate(client, admin_headers)
    match = next(m for m in out["matches"] if m["indicator_key"] == "turbidity_proxy")
    assert match["metric_value"] is None
    assert match["breached"] is None
    assert match["skipped_reason"] is not None
    assert out["pairs_skipped"] >= 1


# ---------------------------------------------------------------- workflow
def test_acknowledge_note_resolve_reopen_workflow(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    sa = default_study_area["id"]
    _create_threshold(
        client, admin_headers,
        indicator_key="rainfall_anomaly",
        indicator_name="Rainfall anomaly",
        operator="lte", value_low=-30.0, unit="mm", approval_status="approved",
    )
    _create_forecast(
        client, admin_headers, study_area_id=sa,
        indicator_key="rainfall_anomaly", value=-45.0, unit="mm",
    )
    out = _evaluate(client, admin_headers)
    alert_id = _match(out, "rainfall_anomaly")["alert_id"]

    # acknowledge
    body = {"note": "Reviewed by ops, monitoring continues"}
    r = client.post(f"/api/v1/disaster/alerts/{alert_id}/acknowledge", json=body, headers=admin_headers)
    assert r.status_code == 200, r.text
    alert = r.json()
    assert alert["status"] == "acknowledged"
    assert alert["acknowledged_by_email"] == "admin@example.org"
    types = [x["response_type"] for x in alert["responses"]]
    assert types == ["acknowledged"]

    # add note (does not change status)
    r = client.post(f"/api/v1/disaster/alerts/{alert_id}/notes", json={"note": "Field team notified"}, headers=admin_headers)
    alert = r.json()
    assert alert["status"] == "acknowledged"
    assert [x["response_type"] for x in alert["responses"]] == ["acknowledged", "note"]

    # resolve
    r = client.post(f"/api/v1/disaster/alerts/{alert_id}/resolve", json={"note": "Conditions returned to normal"}, headers=admin_headers)
    alert = r.json()
    assert alert["status"] == "resolved"
    assert alert["resolved_by_email"] == "admin@example.org"

    # a resolved alert must record the full response history
    detail = client.get(f"/api/v1/disaster/alerts/{alert_id}", headers=admin_headers).json()
    assert [x["response_type"] for x in detail["responses"]] == ["acknowledged", "note", "resolved"]

    # reopen for a renewed breach
    r = client.post(f"/api/v1/disaster/alerts/{alert_id}/reopen", json={"note": "Breach recurred"}, headers=admin_headers)
    alert = r.json()
    assert alert["status"] == "open"
    assert [x["response_type"] for x in alert["responses"]][-1] == "reopened"


def test_each_response_recorded_in_order(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    sa = default_study_area["id"]
    threshold = _create_threshold(
        client, admin_headers,
        indicator_key="water_level_altimetry",
        indicator_name="Water level (altimetry)",   # distinct from the researcher test's gt threshold
        operator="gte", value_low=470.0, unit="m", approval_status="approved",
    )
    _create_forecast(client, admin_headers, study_area_id=sa, indicator_key="water_level_altimetry", value=473.2, unit="m")
    out = _evaluate(client, admin_headers)
    alert_id = _match(out, "water_level_altimetry", threshold["id"])["alert_id"]

    # acknowledge; the re-evaluation below must NOT reset the workflow status
    client.post(f"/api/v1/disaster/alerts/{alert_id}/acknowledge", json={"note": "ack"}, headers=admin_headers)
    _create_forecast(client, admin_headers, study_area_id=sa, indicator_key="water_level_altimetry", value=474.9, unit="m")
    _evaluate(client, admin_headers)
    detail = client.get(f"/api/v1/disaster/alerts/{alert_id}", headers=admin_headers).json()
    assert detail["status"] == "acknowledged"        # preserved
    assert detail["times_seen"] == 2                 # re-evaluation counted
    assert detail["metric_value"] == 474.9           # latest value recorded


def test_alert_annotated_via_workflow_keeps_threshold_snapshot(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    sa = default_study_area["id"]
    threshold = _create_threshold(
        client, admin_headers,
        indicator_key="temperature_anomaly",
        indicator_name="Temperature anomaly",
        operator="gt", value_low=3.0, unit="°C", approval_status="approved",
    )
    _create_forecast(client, admin_headers, study_area_id=sa, indicator_key="temperature_anomaly", value=4.0, unit="°C")
    out = _evaluate(client, admin_headers)
    alert_id = _match(out, "temperature_anomaly", threshold["id"])["alert_id"]
    detail = client.get(f"/api/v1/disaster/alerts/{alert_id}", headers=admin_headers).json()
    assert detail["threshold_id"] == threshold["id"]
    snapshot = detail["threshold_snapshot"]
    assert snapshot["operator"] == "gt" and snapshot["value_low"] == 3.0
    # editing the threshold afterwards must not rewrite the recorded snapshot
    client.patch(
        f"/api/v1/admin/thresholds/{threshold['id']}",
        json={"value_low": 10.0, "change_note": "recalibrated"},
        headers=admin_headers,
    )
    detail = client.get(f"/api/v1/disaster/alerts/{alert_id}", headers=admin_headers).json()
    assert detail["threshold_snapshot"]["value_low"] == 3.0


# ------------------------------------------------------------ permissions
def test_researcher_permissions(client: TestClient, admin_headers: dict[str, str], make_user) -> None:
    _, headers = make_user("disaster-researcher@example.org", role="researcher")
    # read + respond are granted
    assert client.get("/api/v1/disaster/alerts", headers=headers).status_code == 200
    assert client.get("/api/v1/disaster/forecasts", headers=headers).status_code == 200
    # evaluation and forecast writing are not
    assert client.post("/api/v1/disaster/evaluate", json={"dry_run": True}, headers=headers).status_code == 403
    assert client.post(
        "/api/v1/disaster/forecasts",
        json={"indicator_key": "rainfall_summary", "study_area_id": 1, "target_date": "2027-01-01",
              "value": 1.0, "unit": "mm", "note": "nope"},
        headers=headers,
    ).status_code == 403


def test_researcher_can_respond(client: TestClient, admin_headers: dict[str, str], default_study_area: dict, make_user) -> None:
    sa = default_study_area["id"]
    threshold = _create_threshold(
        client, admin_headers,
        indicator_key="water_level_altimetry",
        indicator_name="Water level (altimetry) respond",
        operator="gt", value_low=480.0, unit="m", approval_status="approved",
    )
    _create_forecast(client, admin_headers, study_area_id=sa, indicator_key="water_level_altimetry", value=485.0, unit="m")
    out = _evaluate(client, admin_headers)
    alert_id = _match(out, "water_level_altimetry", threshold["id"])["alert_id"]
    _, headers = make_user("responder@example.org", role="researcher")
    r = client.post(f"/api/v1/disaster/alerts/{alert_id}/acknowledge", json={"note": "from researcher"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "acknowledged"


# ------------------------------------------------------------------- misc
def test_forecast_requires_provenance_note(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    response = client.post(
        "/api/v1/disaster/forecasts",
        json={
            "indicator_key": "rainfall_summary",
            "study_area_id": default_study_area["id"],
            "target_date": "2026-12-01",
            "value": 3.0,
            "unit": "mm",
            "note": "",
        },
        headers=admin_headers,
    )
    assert response.status_code == 422


def test_forecast_rejects_unknown_indicator(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    response = client.post(
        "/api/v1/disaster/forecasts",
        json={
            "indicator_key": "not_an_indicator",
            "study_area_id": default_study_area["id"],
            "target_date": "2026-12-01",
            "value": 3.0,
            "unit": "mm",
            "note": "source: test",
        },
        headers=admin_headers,
    )
    assert response.status_code == 422


def test_evaluation_is_audit_logged(client: TestClient, admin_headers: dict[str, str]) -> None:
    rows = client.get(
        "/api/v1/admin/audit", params={"resource_type": "alert"}, headers=admin_headers
    ).json()
    actions = {r["action"] for r in rows["items"]}
    assert "alert.create" in actions
    assert "disaster.evaluate" in actions
