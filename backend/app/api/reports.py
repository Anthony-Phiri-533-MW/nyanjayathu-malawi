"""Report Generation: build periodic / custom reports and download them."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.serializers import page_response, report_out
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentUser, require_permissions
from app.core.errors import UnprocessableError
from app.schemas.common import Page
from app.schemas.report import ReportCreate, ReportDetailOut, ReportOut
from app.services import reports as service
from app.services.storage import resolve_stored_file

router = APIRouter(prefix="/reports", tags=["reports"])

Create = Annotated[set[str], Depends(require_permissions("reports.create"))]
Read = Annotated[set[str], Depends(require_permissions("reports.read"))]
Download = Annotated[set[str], Depends(require_permissions("reports.download"))]


@router.post("", response_model=ReportOut, status_code=status.HTTP_202_ACCEPTED)
def create_report(
    payload: ReportCreate,
    actor: CurrentUser,
    _perms: Create,
    db: Annotated[Session, Depends(get_db)],
) -> ReportOut:
    _job, report = service.start_report(db, payload=payload, actor=actor)
    db.commit()
    db.refresh(report)
    return report_out(report)


@router.get("", response_model=Page[ReportOut])
def list_reports(
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
    kind: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    period_type: str | None = None,
    study_area_id: int | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> Page[ReportOut]:
    rows, total = service.list_reports(
        db,
        kind=kind,
        status_filter=status_filter,
        period_type=period_type,
        study_area_id=study_area_id,
        page=page,
        size=size,
    )
    return page_response([report_out(r) for r in rows], total, page, size)


@router.get("/{report_id}", response_model=ReportDetailOut)
def get_report(
    report_id: int,
    _perms: Read,
    db: Annotated[Session, Depends(get_db)],
) -> ReportDetailOut:
    row = service.get_report(db, report_id)
    return ReportDetailOut(**report_out(row).model_dump(), summary_json=row.summary_json)


@router.get("/{report_id}/download")
def download_report(
    report_id: int,
    _perms: Download,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    report = service.get_report(db, report_id)
    if report.status != "completed" or not report.file_path or not report.file_name:
        raise UnprocessableError("This report has not completed successfully yet")
    path = resolve_stored_file(report.file_path, allowed_roots=(settings.reports_dir,))
    media_types = {"pdf": "application/pdf", "csv": "text/csv"}
    return FileResponse(
        path,
        media_type=media_types.get(report.format, "application/octet-stream"),
        filename=report.file_name,
    )


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_report(
    report_id: int,
    actor: CurrentUser,
    _perms: Create,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    report = service.get_report(db, report_id)
    service.cancel_report(db, report=report, actor=actor)
    db.commit()


@router.post("/{report_id}/retry", response_model=ReportOut)
def retry_report(
    report_id: int,
    actor: CurrentUser,
    _perms: Create,
    db: Annotated[Session, Depends(get_db)],
) -> ReportOut:
    report = service.get_report(db, report_id)
    updated = service.retry_report(db, report=report, actor=actor)
    db.commit()
    db.refresh(updated)
    return report_out(updated)
