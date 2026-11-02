"""Research: asynchronous exports and file download."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.serializers import export_out, page_response
from app.core.config import settings
from app.core.database import get_db
from app.core.deps import CurrentUser, require_permissions
from app.core.errors import UnprocessableError
from app.schemas.common import Page
from app.schemas.research import ExportCreate, ExportOut
from app.services import exports as service
from app.services.storage import resolve_stored_file

router = APIRouter(prefix="/exports", tags=["research: exports"])

Create = Annotated[set[str], Depends(require_permissions("research.exports.create"))]
Download = Annotated[set[str], Depends(require_permissions("research.exports.download"))]


@router.post("", response_model=ExportOut, status_code=status.HTTP_202_ACCEPTED)
def start_export(
    payload: ExportCreate,
    actor: CurrentUser,
    _perms: Create,
    db: Annotated[Session, Depends(get_db)],
) -> ExportOut:
    job, export = service.start_export(db, payload=payload, actor=actor)
    db.commit()
    db.refresh(export)
    db.refresh(job)
    return export_out(export)


@router.get("", response_model=Page[ExportOut])
def list_exports(
    _perms: Download,
    db: Annotated[Session, Depends(get_db)],
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> Page[ExportOut]:
    rows, total = service.list_exports(db, page=page, size=size)
    return page_response([export_out(r) for r in rows], total, page, size)


@router.get("/{export_id}", response_model=ExportOut)
def get_export(
    export_id: int,
    _perms: Download,
    db: Annotated[Session, Depends(get_db)],
) -> ExportOut:
    return export_out(service.get_export(db, export_id))


@router.get("/{export_id}/download")
def download_export(
    export_id: int,
    _perms: Download,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    export = service.get_export(db, export_id)
    if not export.file_path or not export.file_name:
        raise UnprocessableError("This export has not produced a file yet")
    if (export.job.status if export.job else None) != "succeeded":
        raise UnprocessableError("This export job has not completed successfully")
    path = resolve_stored_file(export.file_path, allowed_roots=(settings.exports_dir,))
    media_types = {
        "csv": "text/csv",
        "json": "application/json",
        "geojson": "application/geo+json",
        "geotiff": "image/tiff",
    }
    return FileResponse(
        path,
        media_type=media_types.get(export.format, "application/octet-stream"),
        filename=export.file_name,
    )
