"""Report Generation service: builds periodic / custom reports from what the
platform has computed - indicator results (summary statistics over the period),
recorded forecast values and disaster alerts - and stores the rendered file in
the file store.

Design notes:

* Reports are a *snapshot*: ``summary_json`` freezes every figure at build
  time, and the rendered file is written once and never regenerated, so what
  was distributed stays auditable.
* There is no separate statistics module; the ``indicators`` section is the
  documented summary statistics (count / min / mean / max / first / last /
  quality-flag distribution) computed here from stored indicator results.
* Rendering is intentionally plain: PDF via reportlab (tables, no charts) and
  a machine-readable long-format CSV.  Content matches for both formats.
* Periodic windows are derived relative to *today* and always end today
  (the platform never claims knowledge of the future).
"""
from __future__ import annotations

import csv
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.database import count_query
from app.core.errors import NotFoundError, UnprocessableError
from app.models import (
    Alert,
    Dataset,
    ForecastValue,
    IndicatorDefinition,
    IndicatorResult,
    Report,
    StudyArea,
    Threshold,
    User,
    utcnow,
)
from app.schemas.report import (
    REPORT_FORMATS,
    REPORT_PERIOD_TYPES,
    REPORT_SECTIONS,
    ReportCreate,
)
from app.services import audit as audit_service
from app.services.jobs import JobContext, enqueue, register_handler
from app.services.storage import new_workspace, relative, sanitize_filename

SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


# ------------------------------------------------------------------ periods
def derive_period(period_type: str, *, today: date | None = None) -> tuple[date, date]:
    """Calendar window for a periodic report; ``period_end`` is today."""
    day = today or datetime.now(UTC).date()
    if period_type == "daily":
        return day, day
    if period_type == "weekly":
        return day - timedelta(days=6), day
    if period_type == "monthly":
        return day.replace(day=1), day
    if period_type == "quarterly":
        quarter_start_month = 3 * ((day.month - 1) // 3) + 1
        return day.replace(month=quarter_start_month, day=1), day
    if period_type == "annual":
        return day.replace(month=1, day=1), day
    raise UnprocessableError(
        f"Unknown period_type '{period_type}'", details={"supported": list(REPORT_PERIOD_TYPES)}
    )


def start_report(db: Session, *, payload: ReportCreate, actor: User) -> tuple[Any, Report]:
    if payload.format not in REPORT_FORMATS:  # pragma: no cover - Literal-guarded
        raise UnprocessableError(f"unsupported report format '{payload.format}'")
    unknown = [s for s in payload.include_sections if s not in REPORT_SECTIONS]
    if unknown:  # pragma: no cover - Literal-guarded
        raise UnprocessableError(f"unknown report section(s): {unknown}")

    if payload.kind == "periodic":
        period_start, period_end = derive_period(str(payload.period_type))
        title = payload.title or f"{payload.period_type.capitalize()} report — {period_start:%d %b %Y}"
    else:
        period_start, period_end = payload.period_start, payload.period_end  # type: ignore[assignment]
        title = payload.title or f"Custom report — {period_start:%d %b %Y} to {period_end:%d %b %Y}"

    if payload.study_area_id is not None and db.get(StudyArea, payload.study_area_id) is None:
        raise NotFoundError("Study area not found", details={"study_area_id": payload.study_area_id})
    if payload.indicator_keys:
        known = {k for (k,) in db.execute(select(IndicatorDefinition.key)).all()}
        unknown_keys = sorted(set(payload.indicator_keys) - known)
        if unknown_keys:
            raise UnprocessableError("Unknown indicator key(s)", details={"unknown": unknown_keys})

    job = enqueue(db, kind="report.build", params={"title": title}, requested_by_id=actor.id)
    db.flush()
    report = Report(
        job_id=job.id,
        title=title,
        kind=payload.kind,
        period_type=payload.period_type,
        period_start=period_start,
        period_end=period_end,
        study_area_id=payload.study_area_id,
        format=payload.format,
        params_json={
            "indicator_keys": payload.indicator_keys,
            "include_sections": list(payload.include_sections),
            "note": payload.note.strip(),
        },
        status="queued",
        created_by_id=actor.id,
    )
    db.add(report)
    db.flush()
    audit_service.record(
        action="report.request",
        resource_type="report",
        resource_id=report.id,
        actor=actor,
        db=db,
        message=f"Requested {payload.format} report '{report.title}' ({period_start} → {period_end})",
        details={
            "kind": report.kind,
            "format": report.format,
            "job_id": job.id,
            "sections": list(payload.include_sections),
        },
    )
    return job, report


# ------------------------------------------------------------- data assembly
def _areas(db: Session, report: Report) -> list[StudyArea]:
    stmt = select(StudyArea).order_by(StudyArea.id.asc())
    if report.study_area_id is not None:
        stmt = stmt.where(StudyArea.id == report.study_area_id)
    return list(db.execute(stmt).scalars())


def _indicators(db: Session, report: Report, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-indicator summary statistics over the report window."""
    keys = params.get("indicator_keys") or []
    stmt = (
        select(
            IndicatorResult.indicator_key,
            func.count(IndicatorResult.id).label("result_count"),
            func.min(IndicatorResult.value).label("min_value"),
            func.max(IndicatorResult.value).label("max_value"),
            func.avg(IndicatorResult.value).label("mean_value"),
            func.count(case((IndicatorResult.value.is_not(None), 1))).label("computed_count"),
        )
        .where(
            IndicatorResult.observed_end >= report.period_start,
            IndicatorResult.observed_start <= report.period_end,
        )
        .group_by(IndicatorResult.indicator_key)
        .order_by(IndicatorResult.indicator_key.asc())
    )
    if report.study_area_id is not None:
        stmt = stmt.where(IndicatorResult.study_area_id == report.study_area_id)
    if keys:
        stmt = stmt.where(IndicatorResult.indicator_key.in_(keys))

    names: dict[str, tuple[str, str, bool]] = {}
    for key, name, unit, is_proxy in db.execute(
        select(
            IndicatorDefinition.key,
            IndicatorDefinition.name,
            IndicatorDefinition.unit,
            IndicatorDefinition.is_proxy,
        )
    ):
        names[key] = (name, unit, bool(is_proxy))

    out: list[dict[str, Any]] = []
    for row in db.execute(stmt).all():
        detail_stmt = (
            select(IndicatorResult.value, IndicatorResult.observed_end, IndicatorResult.quality_flag)
            .where(
                IndicatorResult.indicator_key == row.indicator_key,
                IndicatorResult.observed_end >= report.period_start,
                IndicatorResult.observed_start <= report.period_end,
            )
            .order_by(IndicatorResult.observed_end.asc(), IndicatorResult.id.asc())
        )
        if report.study_area_id is not None:
            detail_stmt = detail_stmt.where(IndicatorResult.study_area_id == report.study_area_id)
        detail = db.execute(detail_stmt).all()
        computed = [(float(value), observed_end) for value, observed_end, _flag in detail if value is not None]
        values = [value for value, _observed_end in computed]
        if computed:
            first_value, first_date = computed[0]
            last_value, last_date = computed[-1]
        else:
            first_value = last_value = None
            first_date = last_date = None
        flags: dict[str, int] = {}
        for _v, _d, q in detail:
            flags[q] = flags.get(q, 0) + 1
        name, unit, is_proxy = names.get(row.indicator_key, (row.indicator_key, "", False))
        mean = float(row.mean_value) if row.mean_value is not None else None
        out.append(
            {
                "indicator_key": row.indicator_key,
                "indicator_name": name,
                "unit": unit,
                "is_proxy": is_proxy,
                "result_count": int(row.result_count),
                "computed_count": int(row.computed_count),
                "min_value": float(row.min_value) if row.min_value is not None else None,
                "max_value": float(row.max_value) if row.max_value is not None else None,
                "mean_value": round(mean, 6) if mean is not None else None,
                "first_value": first_value,
                "first_date": first_date,
                "last_value": last_value,
                "last_date": last_date,
                "direction": _direction(values),
                "quality_flags": flags,
                "note": "remote-sensing proxy (unvalidated)" if is_proxy else "",
            }
        )
    return out


def _direction(values: list[float]) -> str:
    if len(values) < 2:
        return "single value"
    first, last = values[0], values[-1]
    if last > first:
        return "increasing"
    if last < first:
        return "decreasing"
    return "no change"


def _forecasts(db: Session, report: Report) -> list[dict[str, Any]]:
    stmt = (
        select(ForecastValue)
        .where(
            ForecastValue.target_date >= report.period_start,
            ForecastValue.target_date <= report.period_end,
        )
        .order_by(ForecastValue.target_date.asc(), ForecastValue.id.asc())
    )
    if report.study_area_id is not None:
        stmt = stmt.where(ForecastValue.study_area_id == report.study_area_id)
    rows = list(db.execute(stmt).scalars())
    return [
        {
            "id": f.id,
            "indicator_key": f.indicator_key,
            "study_area_id": f.study_area_id,
            "target_date": f.target_date,
            "value": float(f.value),
            "unit": f.unit,
            "note": f.note,
        }
        for f in rows
    ]


def _alerts(db: Session, report: Report) -> dict[str, Any]:
    stmt = select(Alert).where(
        Alert.first_seen_at >= datetime.combine(report.period_start, datetime.min.time()),
        Alert.first_seen_at < datetime.combine(report.period_end + timedelta(days=1), datetime.min.time()),
    )
    if report.study_area_id is not None:
        stmt = stmt.where(Alert.study_area_id == report.study_area_id)
    alerts = list(db.execute(stmt).scalars())
    by_kind: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for a in alerts:
        by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
        by_severity[a.severity] = by_severity.get(a.severity, 0) + 1
        by_status[a.status] = by_status.get(a.status, 0) + 1
    ordered = sorted(alerts, key=lambda a: (-SEVERITY_ORDER.get(a.severity, 0), a.first_seen_at or utcnow()))
    sample = [
        {
            "id": a.id,
            "indicator_key": a.indicator_key,
            "indicator_name": a.indicator_name,
            "kind": a.kind,
            "severity": a.severity,
            "status": a.status,
            "metric_value": float(a.metric_value),
            "unit": a.unit,
            "metric_source": a.metric_source,
            "first_seen_at": a.first_seen_at,
        }
        for a in ordered[:20]
    ]
    highest = ordered[0].severity if ordered else None
    return {
        "total": len(alerts),
        "by_kind": by_kind,
        "by_severity": by_severity,
        "by_status": by_status,
        "highest_severity": highest,
        "sample": sample,
    }


def _overview(db: Session, report: Report, areas: list[StudyArea]) -> dict[str, Any]:
    dataset_stmt = select(func.count(Dataset.id)).where(
        Dataset.start_date <= report.period_end,
        Dataset.end_date >= report.period_start,
    )
    if report.study_area_id is not None:
        dataset_stmt = dataset_stmt.where(Dataset.study_area_id == report.study_area_id)
    datasets = int(db.execute(dataset_stmt).scalar_one())
    thr_stmt = select(Threshold.approval_status, func.count(Threshold.id)).group_by(Threshold.approval_status)
    approvals = {s: int(c) for s, c in db.execute(thr_stmt)}
    return {
        "study_areas": [{"id": a.id, "name": a.name} for a in areas],
        "datasets_overlapping_period": datasets,
        "thresholds": approvals,
        "sections_included": list((report.params_json or {}).get("include_sections") or REPORT_SECTIONS),
        "note": (report.params_json or {}).get("note", ""),
    }


def collect_summary(db: Session, *, report: Report, actor: User | None) -> dict[str, Any]:
    """Everything the report contains, as one JSON snapshot."""
    params = dict(report.params_json or {})
    included = [s for s in params.get("include_sections") or REPORT_SECTIONS if s in REPORT_SECTIONS]
    areas = _areas(db, report)
    summary: dict[str, Any] = {
        "title": report.title,
        "kind": report.kind,
        "period_type": report.period_type,
        "period_start": report.period_start,
        "period_end": report.period_end,
        "study_area_focus": areas[0].name if report.study_area_id is not None and areas else None,
        "format": report.format,
        "generated_at": utcnow(),
        "sections": included,
        "provenance": (
            "All figures are computed from stored platform data at the time of report build. "
            "Indicator statistics are summary statistics of stored results; no external "
            "statistics source and no forecasting is performed. Proxy indicators are "
            "unvalidated remote-sensing estimates."
        ),
    }
    if "overview" in included:
        summary["overview"] = _overview(db, report, areas)
    if "indicators" in included:
        summary["indicators"] = _indicators(db, report, params)
    if "forecasts" in included:
        summary["forecasts"] = _forecasts(db, report)
    if "alerts" in included:
        summary["alerts"] = _alerts(db, report)
    return summary


# ------------------------------------------------------------------ rendering
def _iso_deep(value: Any) -> Any:
    """Recursive ISO normalisation for JSON storage (dates/datetimes only)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _iso_deep(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_iso_deep(v) for v in value]
    return value


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (datetime,)):
        return f"{value:%Y-%m-%d %H:%M}"
    return str(value)


def _render_pdf(summary: dict[str, Any]) -> bytes:
    """Plain, professional PDF: title block + one table per section."""
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "RHeading", parent=styles["Heading2"], fontSize=11, spaceBefore=10, spaceAfter=4
    )
    note = ParagraphStyle(
        "RNote", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#5b6472")
    )

    def table(data: list[list[Any]], widths: list[float] | None = None) -> Table:
        safe_data = [[escape(str(cell)) for cell in row] for row in data]
        t = Table(safe_data, hAlign="LEFT", colWidths=widths)
        t.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8cdd4")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f6")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return t

    story: list[Any] = []
    story.append(Paragraph(escape(str(summary["title"])), styles["Title"]))
    story.append(
        Paragraph(
            f"Period: {summary['period_start']} → {summary['period_end']}"
            + (f" · {summary['period_type']}" if summary.get("period_type") else "")
            + f" · generated {summary['generated_at']:%Y-%m-%d %H:%M} UTC",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Provenance", heading))
    story.append(Paragraph(escape(str(summary["provenance"])), note))
    if "overview" in summary and summary["overview"].get("note"):
        story.append(Paragraph(f"Requested note: {escape(str(summary['overview']['note']))}", note))
    story.append(Spacer(1, 3 * mm))

    if "overview" in summary["sections"]:
        ov = summary["overview"]
        story.append(Paragraph("Overview", heading))
        story.append(
            table(
                [
                    ["Item", "Value"],
                    ["Study areas", ", ".join(a["name"] for a in ov["study_areas"]) or "—"],
                    ["Datasets overlapping period", ov["datasets_overlapping_period"]],
                    ["Approved thresholds", ov["thresholds"].get("approved", 0)],
                    ["Provisional thresholds", ov["thresholds"].get("provisional", 0)],
                ],
                [60 * mm, 90 * mm],
            )
        )
        story.append(Spacer(1, 3 * mm))

    if "indicators" in summary["sections"]:
        story.append(Paragraph("Indicator summary statistics", heading))
        rows = [
            [
                "Indicator", "Count", "Min", "Mean", "Max", "First → Last", "Trend", "Quality flags",
            ]
        ]
        for ind in summary["indicators"]:
            rows.append(
                [
                    f"{ind['indicator_name'] or ind['indicator_key']}"
                    + (f" ({ind['unit']})" if ind["unit"] else ""),
                    _fmt(ind["result_count"]),
                    _fmt(ind["min_value"]),
                    _fmt(ind["mean_value"]),
                    _fmt(ind["max_value"]),
                    f"{_fmt(ind['first_value'])} @ {ind['first_date']} → {_fmt(ind['last_value'])} @ {ind['last_date']}",
                    _fmt(ind["direction"]),
                    ", ".join(f"{k}×{v}" for k, v in ind["quality_flags"].items()),
                ]
            )
        if len(rows) == 1:
            rows.append(["No computed indicator results in this period", "—", "—", "—", "—", "—", "—", "—"])
        story.append(table(rows))
        proxy_names = [
            (ind["indicator_name"] or ind["indicator_key"])
            for ind in summary["indicators"]
            if ind["is_proxy"]
        ]
        if proxy_names:
            story.append(
                Paragraph(
                    "Unvalidated remote-sensing proxies included: " + ", ".join(proxy_names) + ".", note
                )
            )
        story.append(Spacer(1, 3 * mm))

    if "forecasts" in summary["sections"]:
        story.append(Paragraph("Forecast values in period (user-recorded)", heading))
        rows = [["Indicator", "Study area ID", "Target date", "Value", "Provenance note"]]
        for f in summary["forecasts"]:
            rows.append([f["indicator_key"], f["study_area_id"], f["target_date"], f"{f['value']} {f['unit']}", f["note"]])
        if len(rows) == 1:
            rows.append(["No forecast values recorded in this period", "—", "—", "—", "—"])
        story.append(table(rows, [35 * mm, 22 * mm, 22 * mm, 22 * mm, 49 * mm]))
        story.append(Spacer(1, 3 * mm))

    if "alerts" in summary["sections"]:
        al = summary["alerts"]
        story.append(Paragraph("Disaster alerts in period", heading))
        story.append(
            table(
                [
                    ["Item", "Value"],
                    ["Alerts first seen", al["total"]],
                    ["By kind", ", ".join(f"{k}: {v}" for k, v in sorted(al["by_kind"].items())) or "—"],
                    ["By severity", ", ".join(f"{k}: {v}" for k, v in sorted(al["by_severity"].items())) or "—"],
                    ["By status", ", ".join(f"{k}: {v}" for k, v in sorted(al["by_status"].items())) or "—"],
                    ["Highest severity", _fmt(al["highest_severity"])],
                ],
                [60 * mm, 90 * mm],
            )
        )
        if al["sample"]:
            story.append(Spacer(1, 2 * mm))
            rows = [["ID", "Indicator", "Kind", "Severity", "Status", "Value", "Source"]]
            for a in al["sample"]:
                rows.append(
                    [a["id"], a["indicator_name"] or a["indicator_key"], a["kind"], a["severity"],
                     a["status"], f"{a['metric_value']} {a['unit']}", a["metric_source"]]
                )
            story.append(table(rows, [10 * mm, 48 * mm, 22 * mm, 20 * mm, 24 * mm, 25 * mm, 16 * mm]))

    from io import BytesIO

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=summary["title"])
    doc.build(story)
    return buf.getvalue()


def _render_csv(summary: dict[str, Any]) -> bytes:
    """Long-format CSV: one ``section,name,metric,value,unit,detail`` table."""
    from io import StringIO

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["section", "name", "metric", "value", "unit", "detail"])

    def row(section: str, name: str, metric: str, value: Any, unit: str = "", detail: str = "") -> None:
        writer.writerow([section, name, metric, _fmt(value), unit, _fmt(detail)])

    row("report", summary["title"], "kind", summary["kind"], detail=f"{summary['period_start']} → {summary['period_end']}")
    row("report", "", "generated_at", summary["generated_at"])
    row("report", "", "provenance", summary["provenance"])

    if "overview" in summary["sections"]:
        ov = summary["overview"]
        row("overview", "", "study_areas", "; ".join(a["name"] for a in ov["study_areas"]))
        row("overview", "", "datasets_overlapping_period", ov["datasets_overlapping_period"])
        for status, count in sorted(ov["thresholds"].items()):
            row("overview", "", f"thresholds_{status}", count)

    if "indicators" in summary["sections"]:
        if summary["indicators"]:
            for ind in summary["indicators"]:
                name = ind["indicator_name"] or ind["indicator_key"]
                row("indicators", name, "result_count", ind["result_count"])
                row("indicators", name, "min_value", ind["min_value"], ind["unit"])
                row("indicators", name, "mean_value", ind["mean_value"], ind["unit"])
                row("indicators", name, "max_value", ind["max_value"], ind["unit"])
                row("indicators", name, "first_value", ind["first_value"], ind["unit"], ind["first_date"])
                row("indicators", name, "last_value", ind["last_value"], ind["unit"], ind["last_date"])
                row("indicators", name, "trend", ind["direction"])
                for flag, count in sorted(ind["quality_flags"].items()):
                    row("indicators", name, f"quality_{flag}", count)
                if ind["is_proxy"]:
                    row("indicators", name, "proxy", "unvalidated remote-sensing estimate")
        else:
            row("indicators", "", "computed_results", 0, detail="none in period")

    if "forecasts" in summary["sections"]:
        forecasts = summary["forecasts"]
        if forecasts:
            for f in forecasts:
                row("forecasts", f["indicator_key"], "value", f["value"], f["unit"],
                    f"target {f['target_date']}; {f['note']}")
        else:
            row("forecasts", "", "recorded_values", 0, detail="none in period")

    if "alerts" in summary["sections"]:
        al = summary["alerts"]
        row("alerts", "", "total", al["total"])
        for k, v in sorted(al["by_kind"].items()):
            row("alerts", k, "count", v)
        for k, v in sorted(al["by_severity"].items()):
            row("alerts", "", f"severity_{k}", v)
        for k, v in sorted(al["by_status"].items()):
            row("alerts", "", f"status_{k}", v)
        row("alerts", "", "highest_severity", al["highest_severity"])
        for a in al["sample"]:
            row("alerts", a["indicator_name"] or a["indicator_key"], f"alert_{a['id']}",
                f"{a['metric_value']} {a['unit']}",
                detail=f"kind={a['kind']} severity={a['severity']} status={a['status']} source={a['metric_source']}")

    return buf.getvalue().encode("utf-8-sig")


def run_report(
    db: Session,
    *,
    report: Report,
    job_id: int | None = None,
    actor: User | None = None,
    progress=None,
) -> dict[str, Any]:
    if report.format not in REPORT_FORMATS:
        raise UnprocessableError(f"unsupported report format '{report.format}'")
    if progress:
        progress(0.2, "collecting report data")
    summary = collect_summary(db, report=report, actor=actor)
    if progress:
        progress(0.6, f"rendering {report.format}")

    workdir = new_workspace("reports")
    stem = sanitize_filename(
        f"report_{report.period_start:%Y%m%d}_{report.period_end:%Y%m%d}_{uuid.uuid4().hex[:6]}",
        fallback="report",
    )
    path = workdir / f"{stem}.{'pdf' if report.format == 'pdf' else 'csv'}"
    content = _render_pdf(summary) if report.format == "pdf" else _render_csv(summary)
    path.write_bytes(content)

    report.summary_json = _iso_deep(summary)
    report.file_path = relative(path)
    report.file_name = path.name
    report.size_bytes = len(content)
    report.status = "completed"
    report.error = None
    report.completed_at = utcnow()
    db.flush()
    if progress:
        progress(1.0, "report written")
    audit_service.record(
        action="report.complete",
        resource_type="report",
        resource_id=report.id,
        actor=actor,
        db=db,
        message=f"Report '{report.title}' built ({report.format.upper()}, {len(content)} bytes)",
        details={"file": report.file_name, "sections": summary["sections"]},
    )
    return {
        "report_id": report.id,
        "format": report.format,
        "file_name": report.file_name,
        "size_bytes": len(content),
    }


@register_handler("report.build")
def handle_report_job(ctx: JobContext) -> dict:
    report = ctx.db.execute(
        select(Report).where(Report.job_id == ctx.job.id)
    ).scalar_one_or_none()
    if report is None:
        raise UnprocessableError("Report record for this job is missing")
    report.status = "building"
    ctx.db.commit()
    try:
        return run_report(ctx.db, report=report, job_id=ctx.job.id, actor=ctx.actor, progress=ctx.progress)
    except Exception as exc:
        # the job runner rolls its session back, so persist the report failure
        # ourselves; only mark permanently failed when no attempt is left.
        ctx.db.rollback()
        ctx.db.refresh(report)
        final = ctx.job.attempts >= ctx.job.max_attempts
        report.status = "failed" if final else "queued"
        if final:
            report.error = f"{type(exc).__name__}: {exc}"[:2000]
            report.completed_at = utcnow()
        ctx.db.commit()
        raise


def get_report(db: Session, report_id: int) -> Report:
    report = db.get(Report, report_id)
    if report is None:
        raise NotFoundError(f"Report {report_id} not found")
    return report


def list_reports(
    db: Session,
    *,
    kind: str | None = None,
    status_filter: str | None = None,
    period_type: str | None = None,
    study_area_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Report], int]:
    stmt = select(Report)
    if kind:
        stmt = stmt.where(Report.kind == kind)
    if status_filter:
        stmt = stmt.where(Report.status == status_filter)
    if period_type:
        stmt = stmt.where(Report.period_type == period_type)
    if study_area_id is not None:
        stmt = stmt.where(Report.study_area_id == study_area_id)
    total = count_query(stmt, db)
    rows = list(
        db.execute(
            stmt.order_by(Report.created_at.desc(), Report.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return rows, total


def cancel_report(db: Session, *, report: Report, actor: User | None) -> Report:
    """Cancel a report whose job is still waiting in the queue."""
    if report.status in ("completed", "failed", "canceled"):
        raise UnprocessableError(
            f"Cannot cancel a report with status '{report.status}'"
        )
    from app.services import jobs as jobs_service

    job = report.job
    if report.status != "queued" or job is None or job.status != "pending":
        raise UnprocessableError("A report can only be canceled before its build starts")
    jobs_service.cancel_job(db, job)
    report.status = "canceled"
    report.error = "Cancelled by user"
    report.completed_at = utcnow()
    db.flush()
    audit_service.record(
        action="report.cancel",
        resource_type="report",
        resource_id=report.id,
        actor=actor,
        db=db,
        message=f"Cancelled report '{report.title}'",
    )
    return report


def retry_report(db: Session, *, report: Report, actor: User | None) -> Report:
    """Re-queue a failed or canceled report for another build attempt."""
    if report.status not in ("failed", "canceled"):
        raise UnprocessableError(
            f"Only failed or canceled reports can be retried (current status: '{report.status}')"
        )
    from app.services import jobs as jobs_service

    job = report.job
    if job is None or job.status not in ("failed", "canceled"):
        raise UnprocessableError("The report job is not eligible for retry")
    jobs_service.retry_job(db, job)
    report.status = "queued"
    report.error = None
    report.completed_at = None
    db.flush()
    audit_service.record(
        action="report.retry",
        resource_type="report",
        resource_id=report.id,
        actor=actor,
        db=db,
        message=f"Retry queued for report '{report.title}'",
    )
    return report
