"""Disaster Management service: the threshold comparison engine, alert
workflow and response records.

How evaluation works (documented, testable, and honest about its inputs):

1. Resolve the enabled thresholds to evaluate.  By default only
   ``approval_status == "approved"`` thresholds participate; provisional ones
   are included only when explicitly requested and are labelled as such in the
   alert message.  The threshold snapshot is stored on the alert so later
   threshold edits never rewrite what was breached.
2. For every (study area, indicator with a threshold) pair, resolve the most
   recent metric value available, in this priority order:
   - the latest recorded **forecast** value for that pair
     (user-entered, provenance required, ``metric_source="forecast"``);
   - the latest **computed indicator result** with a non-null value
     (``metric_source="observed"``).
   When no metric exists the pair is skipped with an explicit reason - the
   engine never invents values.
3. A breach is raised per the threshold operator:
   ``gt/gte``  -> breach when  value >/>= value_low
   ``lt/lte``  -> breach when  value </<= value_low
   ``between`` -> value_low..value_high is the *normal band*; a breach is any
   value outside it.
4. Severity is derived from the exceedance magnitude with provisional default
   bands (see :func:`severity_for`): ``critical`` when the value is beyond the
   threshold by >= 25% of the reference scale, else ``warning``.  These bands
   are a starting point, deliberately conservative, and are recorded in the
   alert message; calibrating them for Lake Malawi requires validated data.
5. The hazard class (`kind`) is mapped from the indicator and breach direction
   (see :func:`kind_for`) - e.g. high water level / water extent is ``flood``,
   low rainfall anomaly is ``drought``.  High temperature is ``general`` (use
   the alert type in line with local conventions).
6. Dedupe: while an alert for the same (study area, indicator, threshold) is
   still open, re-evaluation updates it (value, date, ``times_seen``, severity
   escalation) instead of creating duplicates.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.database import count_query
from app.core.errors import NotFoundError, UnprocessableError
from app.models import (
    Alert,
    AlertResponse,
    ForecastValue,
    IndicatorDefinition,
    IndicatorResult,
    StudyArea,
    Threshold,
    User,
    utcnow,
)
from app.schemas.disaster import (
    AlertActionCreate,
    EvaluateMatch,
    EvaluateOut,
    EvaluateRequest,
    ForecastCreate,
)
from app.services import audit as audit_service

# provisional severity bands: fraction by which the value exceeds the
# threshold reference (or the band width for "between") before "critical".
CRITICAL_EXCEEDANCE = 0.25
CRITICAL_EXCEEDANCE_BETWEEN = 0.25   # of the band width outside the band

# indicator key -> breach direction -> hazard class.  Documented provisional
# mapping; "general" is used where no convention is justified yet.
_KIND_MAP: dict[str, dict[str, str]] = {
    # high water level / extent -> flood; low -> drying lake
    "water_level_altimetry": {"gt": "flood", "gte": "flood", "lt": "drought", "lte": "drought"},
    "water_extent": {"gt": "flood", "gte": "flood", "lt": "drought", "lte": "drought"},
    "water_extent_change": {"gt": "flood", "gte": "flood", "lt": "drought", "lte": "drought"},
    # rainfall shortfall -> drought; exceptional rainfall -> flood risk
    "rainfall_anomaly": {"gt": "flood", "gte": "flood", "lt": "drought", "lte": "drought"},
    "rainfall_summary": {"lt": "drought", "lte": "drought", "gt": "flood", "gte": "flood"},
    # exceed proxies -> water-quality hazard
    "chlorophyll_a_proxy": {"gt": "water_quality", "gte": "water_quality"},
    "turbidity_proxy": {"gt": "water_quality", "gte": "water_quality", "lt": "general", "lte": "general"},
}

_UNDEF = "general"


def kind_for(indicator_key: str, operator: str) -> str:
    """Provisional indicator/direction -> hazard-class mapping."""
    return _KIND_MAP.get(indicator_key, {}).get(operator, _UNDEF)


def severity_for(threshold: Threshold, value: float) -> str:
    """Provisional exceedance -> severity bands (see module docstring)."""
    op = threshold.operator
    if op in ("gt", "gte", "lt", "lte"):
        reference = abs(float(threshold.value_low or 0.0))
        exceedance = (
            (value - float(threshold.value_low)) / reference if reference > 0
            else None
        ) if op in ("gt", "gte") else (
            (float(threshold.value_low) - value) / reference if reference > 0 else None
        )
    else:  # between: distance outside the band relative to the band width
        low = float(threshold.value_low)
        high = float(threshold.value_high)
        width = max(high - low, 1e-9)
        distance = 0.0
        if value < low:
            distance = low - value
        elif value > high:
            distance = value - high
        exceedance = distance / width

    if exceedance is None:
        # zero-valued reference threshold cannot express a fraction; default to
        # warning so any breach at least notifies (documented behaviour).
        return "warning"
    return "critical" if exceedance >= CRITICAL_EXCEEDANCE else "warning"


def breached(threshold: Threshold, value: float) -> bool:
    """Breach rule per operator (see module docstring)."""
    low = threshold.value_low
    high = threshold.value_high
    op = threshold.operator
    if op == "gt":
        return value > float(low)
    if op == "gte":
        return value >= float(low)
    if op == "lt":
        return value < float(low)
    if op == "lte":
        return value <= float(low)
    if op == "between":
        return value < float(low) or value > float(high)
    raise UnprocessableError(f"Unknown threshold operator '{op}'")


def _message(
    *,
    indicator_name: str,
    source: str,
    value: float,
    unit: str,
    threshold: Threshold,
    severity: str,
    provisional: bool,
) -> str:
    op_text = {
        "gt": f"above {threshold.value_low}",
        "gte": f"at or above {threshold.value_low}",
        "lt": f"below {threshold.value_low}",
        "lte": f"at or below {threshold.value_low}",
        "between": f"outside the {threshold.value_low}–{threshold.value_high} band",
    }.get(threshold.operator, threshold.operator)
    label = f"{source.capitalize()} {indicator_name}"
    band = " (provisional threshold)" if provisional else ""
    return (
        f"{label} {value:g} {unit} is {op_text}{band}; "
        f"severity {severity} per provisional exceedance bands"
    )


# ------------------------------------------------------------------ forecasts
def list_forecasts(
    db: Session,
    *,
    study_area_id: int | None = None,
    indicator_key: str | None = None,
    page: int = 1,
    size: int = 50,
) -> tuple[list[ForecastValue], int]:
    stmt = select(ForecastValue).order_by(ForecastValue.target_date.desc(), ForecastValue.id.desc())
    if study_area_id is not None:
        stmt = stmt.where(ForecastValue.study_area_id == study_area_id)
    if indicator_key:
        stmt = stmt.where(ForecastValue.indicator_key == indicator_key)
    total = count_query(stmt, db)
    rows = db.execute(stmt.limit(size).offset((page - 1) * size)).scalars().all()
    return list(rows), total


def record_forecast(db: Session, *, payload: ForecastCreate, actor: User) -> ForecastValue:
    study_area = db.get(StudyArea, payload.study_area_id)
    if study_area is None:
        raise NotFoundError("Study area not found", details={"study_area_id": payload.study_area_id})
    definition = db.execute(
        select(IndicatorDefinition).where(IndicatorDefinition.key == payload.indicator_key)
    ).scalar_one_or_none()
    if definition is None:
        raise UnprocessableError(
            f"Unknown indicator '{payload.indicator_key}'",
            details={"supported": sorted(
                k for (k,) in db.execute(select(IndicatorDefinition.key)).all()
            )},
        )
    row = ForecastValue(
        study_area_id=payload.study_area_id,
        indicator_key=payload.indicator_key,
        target_date=payload.target_date,
        value=payload.value,
        unit=payload.unit,
        note=payload.note.strip(),
        created_at=utcnow(),
        created_by_id=actor.id,
    )
    db.add(row)
    db.flush()
    audit_service.record(
        action="forecast.create",
        resource_type="forecast",
        resource_id=row.id,
        actor=actor,
        db=db,
        message=f"Recorded forecast for {row.indicator_key} ({study_area.name}) on {row.target_date}",
        details={
            "indicator_key": row.indicator_key,
            "study_area_id": row.study_area_id,
            "target_date": row.target_date.isoformat(),
            "value": row.value,
            "unit": row.unit,
            "note": row.note,
        },
    )
    return row


# ------------------------------------------------------------------ evaluation
def evaluate(db: Session, *, payload: EvaluateRequest, actor: User) -> EvaluateOut:
    threshold_stmt = select(Threshold).where(Threshold.is_enabled.is_(True))
    if payload.include_provisional:
        threshold_stmt = threshold_stmt.where(
            Threshold.approval_status.in_(["approved", "provisional"])
        )
    else:
        threshold_stmt = threshold_stmt.where(Threshold.approval_status == "approved")
    thresholds = list(db.execute(threshold_stmt).scalars().all())
    if payload.indicator_keys:
        wanted = set(payload.indicator_keys)
        thresholds = [t for t in thresholds if t.indicator_key in wanted]

    areas = list(db.execute(select(StudyArea)).scalars().all())
    if payload.study_area_ids:
        wanted = set(payload.study_area_ids)
        areas = [a for a in areas if a.id in wanted]

    results = EvaluateOut(
        dry_run=payload.dry_run,
        include_provisional=payload.include_provisional,
        thresholds_used=len(thresholds),
        pairs_considered=0,
        pairs_skipped=0,
        breached=0,
        alerts_created=0,
        alerts_updated=0,
        matches=[],
    )
    if not thresholds:
        return results

    for area in areas:
        for t in thresholds:
            results.pairs_considered += 1
            match = EvaluateMatch(
                study_area_id=area.id,
                study_area_name=area.name,
                indicator_key=t.indicator_key,
                threshold_id=t.id,
                metric_source="observed",   # placeholder; corrected below
                metric_value=None,
                metric_date=None,
                breached=None,
                severity=None,
                alert_id=None,
                skipped_reason=None,
            )
            found = _latest_metric(db, study_area_id=area.id, indicator_key=t.indicator_key)
            if found is None:
                results.pairs_skipped += 1
                match.skipped_reason = "no forecast value or computed indicator result for this indicator/study area"
                results.matches.append(match)
                continue
            source, value, metric_date, provisional_metric = found
            match.metric_source = source   # type: ignore[assignment]
            match.metric_value = value
            match.metric_date = metric_date
            if not breached(t, value):
                match.breached = False
                results.matches.append(match)
                continue
            match.breached = True
            results.breached += 1
            severity = severity_for(t, value)
            match.severity = severity
            provisional = t.approval_status != "approved"
            message = _message(
                indicator_name=t.indicator_name,
                source=source,
                value=value,
                unit=t.unit,
                threshold=t,
                severity=severity,
                provisional=provisional,
            )
            if payload.dry_run:
                results.matches.append(match)
                continue
            alert = _upsert_alert(
                db,
                area=area,
                threshold=t,
                source=source,
                value=value,
                metric_date=metric_date,
                provisional_metric=provisional_metric,
                severity=severity,
                message=message,
                provisional_threshold=provisional,
            )
            if alert.id is not None:
                match.alert_id = alert.id
            if alert.times_seen == 1 and alert.first_seen_at == alert.last_evaluated_at:
                results.alerts_created += 1
            else:
                results.alerts_updated += 1
            results.matches.append(match)

    if not payload.dry_run and (results.alerts_created or results.alerts_updated):
        db.flush()
        audit_service.record(
            action="disaster.evaluate",
            resource_type="alert",
            actor=actor,
            db=db,
            message=(
                f"Threshold evaluation: {results.alerts_created} created, "
                f"{results.alerts_updated} updated, {results.breached} breaches, "
                f"{results.pairs_skipped} skipped"
            ),
            details={
                "thresholds_used": results.thresholds_used,
                "pairs_considered": results.pairs_considered,
                "include_provisional": payload.include_provisional,
                "dry_run": payload.dry_run,
            },
        )
    return results


def _latest_metric(
    db: Session, *, study_area_id: int, indicator_key: str
) -> tuple[str, float, Any, bool] | None:
    """Latest available metric for a pair.

    Returns ``(source, value, date, is_provisional_metric)`` or ``None``.
    Forecast values take priority (they represent the user's projected
    conditions); otherwise the latest computed indicator result with a value
    is used. ``is_provisional_metric`` marks proxy indicators whose values are
    estimates (chlorophyll-a / turbidity), so the alert message can say so.
    """
    forecast = db.execute(
        select(ForecastValue)
        .where(
            ForecastValue.study_area_id == study_area_id,
            ForecastValue.indicator_key == indicator_key,
        )
        .order_by(ForecastValue.target_date.desc(), ForecastValue.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if forecast is not None:
        return ("forecast", float(forecast.value), forecast.target_date, False)

    result = db.execute(
        select(IndicatorResult, IndicatorDefinition.is_proxy)
        .join(IndicatorDefinition, IndicatorDefinition.id == IndicatorResult.definition_id)
        .where(
            IndicatorResult.study_area_id == study_area_id,
            IndicatorResult.indicator_key == indicator_key,
            IndicatorResult.value.is_not(None),
        )
        .order_by(IndicatorResult.observed_end.desc(), IndicatorResult.id.desc())
        .limit(1)
    ).first()
    if result is None:
        return None
    row, is_proxy = result
    return ("observed", float(row.value), row.observed_end, bool(is_proxy))


def _upsert_alert(
    db: Session,
    *,
    area: StudyArea,
    threshold: Threshold,
    source: str,
    value: float,
    metric_date: Any,
    provisional_metric: bool,
    severity: str,
    message: str,
    provisional_threshold: bool,
) -> Alert:
    existing = db.execute(
        select(Alert)
        .where(
            Alert.study_area_id == area.id,
            Alert.indicator_key == threshold.indicator_key,
            Alert.threshold_id == threshold.id,
            Alert.status.in_(["open", "acknowledged"]),
        )
        .order_by(Alert.id.asc())
        .limit(1)
    ).scalar_one_or_none()

    if provisional_metric:
        message += "; note: this value is an unvalidated remote-sensing proxy"

    if existing is not None:
        existing.metric_value = value
        existing.metric_date = metric_date
        existing.times_seen = (existing.times_seen or 1) + 1
        existing.last_evaluated_at = utcnow()
        # escalate severity, never silently downgrade
        order = {"info": 0, "warning": 1, "critical": 2}
        if order.get(severity, 1) > order.get(existing.severity, 1):
            existing.severity = severity
            existing.message = message
        db.add(AlertResponse(
            alert_id=existing.id,
            response_type="note",
            note=f"Re-evaluated: {message}",
            created_at=utcnow(),
        ))
        audit_service.record(
            action="alert.update",
            resource_type="alert",
            resource_id=existing.id,
            db=db,
            message=f"Alert re-triggered for {existing.indicator_key} ({existing.times_seen}x)",
            details={"value": value, "metric_date": str(metric_date)},
        )
        return existing

    alert = Alert(
        study_area_id=area.id,
        indicator_key=threshold.indicator_key,
        indicator_name=threshold.indicator_name,
        threshold_id=threshold.id,
        threshold_snapshot_json={
            "operator": threshold.operator,
            "value_low": threshold.value_low,
            "value_high": threshold.value_high,
            "approval_status": threshold.approval_status,
            "version": threshold.version,
            "reference": threshold.reference,
        },
        metric_source="forecast" if source == "forecast" else "observed",
        metric_value=value,
        metric_date=metric_date,
        unit=threshold.unit,
        kind=kind_for(threshold.indicator_key, threshold.operator),
        severity=severity,
        status="open",
        message=message,
        first_seen_at=utcnow(),
        last_evaluated_at=utcnow(),
        times_seen=1,
    )
    db.add(alert)
    db.flush()
    audit_service.record(
        action="alert.create",
        resource_type="alert",
        resource_id=alert.id,
        db=db,
        message=f"Alert created: {message}",
        details={
            "indicator_key": alert.indicator_key,
            "study_area_id": area.id,
            "metric_source": alert.metric_source,
            "kind": alert.kind,
            "severity": alert.severity,
        },
    )
    return alert


# ------------------------------------------------------------------ alerts
def list_alerts(
    db: Session,
    *,
    status_filter: str | None = None,
    severity: str | None = None,
    kind: str | None = None,
    study_area_id: int | None = None,
    metric_source: str | None = None,
    indicator_key: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Alert], int]:
    stmt = select(Alert).options(joinedload(Alert.study_area))
    if status_filter:
        stmt = stmt.where(Alert.status == status_filter)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if kind:
        stmt = stmt.where(Alert.kind == kind)
    if metric_source:
        stmt = stmt.where(Alert.metric_source == metric_source)
    if indicator_key:
        stmt = stmt.where(Alert.indicator_key == indicator_key)
    if study_area_id is not None:
        stmt = stmt.where(Alert.study_area_id == study_area_id)
    total = count_query(stmt, db)
    rows = db.execute(
        stmt.order_by(
            Alert.severity.desc(), Alert.first_seen_at.desc(), Alert.id.desc()
        ).limit(size).offset((page - 1) * size)
    ).unique().scalars().all()
    return list(rows), total


def get_alert(db: Session, alert_id: int) -> Alert:
    alert = db.execute(
        select(Alert).where(Alert.id == alert_id)
    ).unique().scalar_one_or_none()
    if alert is None:
        raise NotFoundError("Alert not found", details={"alert_id": alert_id})
    return alert


_ACTION_TO_TYPE = {"acknowledge": "acknowledged", "resolve": "resolved", "reopen": "reopened", "note": "note"}


def respond(
    db: Session,
    *,
    alert: Alert,
    action: str,
    payload: AlertActionCreate,
    actor: User,
) -> Alert:
    response_type = _ACTION_TO_TYPE.get(action)
    if response_type is None:
        raise UnprocessableError(f"Unknown alert action '{action}'")
    if action in ("acknowledge", "resolve") and alert.status == "resolved" and action == "acknowledge":
        raise UnprocessableError("Cannot acknowledge a resolved alert; reopen it first")

    now = utcnow()
    if action == "acknowledge":
        if payload.severity is not None:
            alert.severity = payload.severity
        if payload.kind is not None:
            alert.kind = payload.kind
        alert.status = "acknowledged"
        alert.acknowledged_at = now
        alert.acknowledged_by_id = actor.id
    elif action == "resolve":
        if payload.severity is not None:
            alert.severity = payload.severity
        alert.status = "resolved"
        alert.resolved_at = now
        alert.resolved_by_id = actor.id
    elif action == "reopen":
        if alert.status == "open":
            raise UnprocessableError("Alert is already open")
        alert.status = "open"
        alert.resolved_at = None
        alert.resolved_by_id = None
    # "note" changes nothing but the record itself

    db.add(AlertResponse(
        alert_id=alert.id,
        response_type=response_type,
        note=payload.note.strip(),
        actor_id=actor.id,
        created_at=now,
    ))
    db.flush()
    audit_service.record(
        action=f"alert.{action}",
        resource_type="alert",
        resource_id=alert.id,
        actor=actor,
        db=db,
        message=f"Alert {alert.id} ({alert.indicator_key}): {action}"
        + (f" — {payload.note.strip()}" if payload.note.strip() else ""),
        details={"response_type": response_type, "note": payload.note.strip()}
        | ({"severity": payload.severity} if payload.severity else {})
        | ({"kind": payload.kind} if payload.kind else {}),
    )
    return alert
