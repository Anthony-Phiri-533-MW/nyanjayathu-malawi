"""Filesystem storage abstraction.

All persisted files live under ``settings.storage_root`` (raw inputs,
processed products, exports) below the configured root, referenced by
relative POSIX paths.  ``resolve_stored_file`` is the single choke point for
turning a stored reference into a real path and rejects anything that escapes
the storage root (path-traversal protection).  The layout is object-storage
friendly: swapping in S3/GCS later only requires re-implementing this module.
"""
from __future__ import annotations

import hashlib
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.core.errors import AppError


def ensure_storage_dirs() -> None:
    for d in (settings.raw_dir, settings.processed_dir, settings.exports_dir, settings.reports_dir, settings.tmp_dir):
        d.mkdir(parents=True, exist_ok=True)


def relative(path: Path) -> str:
    """Storage-relative POSIX path for the database."""
    return path.resolve().relative_to(settings.storage_root.resolve()).as_posix()


def absolute(rel_path: str) -> Path:
    return settings.storage_root / Path(rel_path)


def resolve_stored_file(rel_path: str, *, allowed_roots: tuple[Path, ...] | None = None) -> Path:
    """Validate a stored path and return the absolute path.

    Raises AppError when the path escapes the storage root or does not exist.
    """
    roots = allowed_roots or (settings.storage_root,)
    candidate = Path(rel_path)
    if candidate.is_absolute():
        raise AppError("Absolute file paths are not accepted", code="invalid_path")
    resolved = (settings.storage_root / candidate).resolve()
    ok = any(_is_relative_to(resolved, root.resolve()) for root in roots)
    if not ok:
        raise AppError("File path is outside the storage root", code="invalid_path")
    if not resolved.is_file():
        raise AppError("File not found", code="not_found")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def new_workspace(kind: str) -> Path:
    """Create ``<kind>/<YYYY>/<MM>/<uuid>`` under the matching storage area."""
    now = datetime.now(UTC)
    area = {
        "raw": settings.raw_dir,
        "processed": settings.processed_dir,
        "exports": settings.exports_dir,
        "reports": settings.reports_dir,
    }[kind]
    path = area / f"{now:%Y}" / f"{now:%m}" / uuid.uuid4().hex[:16]
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_checksum(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_copy(src: Path, dst: Path) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst.stat().st_size


def sanitize_filename(name: str, *, fallback: str = "export") -> str:
    keep = "".join(c if c.isalnum() or c in "-._" else "_" for c in name)
    keep = keep.strip("._") or fallback
    return keep[:180]
