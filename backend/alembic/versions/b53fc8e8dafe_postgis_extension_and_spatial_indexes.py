"""postgis extension and spatial indexes

Adds PostGIS to PostgreSQL deployments and puts GiST indexes on the GeoJSON
columns that are queried by bounding box (``app.services.spatial``).  Geometry
is stored as GeoJSON text so the schema works unchanged on SQLite; these
objects are what makes the PostGIS pushdown path fast.

Every step is a no-op on SQLite and on PostgreSQL without superuser rights to
install extensions (the application then falls back to in-process filtering).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'b53fc8e8dafe'
down_revision = 'ba20bc51427c'
branch_labels = None
depends_on = None


# (table, GeoJSON column, index name) that benefit from a spatial index.
_SPATIAL_COLUMNS = [
    ("study_areas", "boundary_geojson", "ix_study_areas_boundary_geom_gist"),
    ("datasets", "coverage_geojson", "ix_datasets_coverage_geom_gist"),
]


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    # May fail on managed databases where the extension is pre-installed or
    # the role cannot create extensions; the application degrades gracefully.
    try:
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    except Exception:  # pragma: no cover - environment dependent
        return

    for table, column, index_name in _SPATIAL_COLUMNS:
        op.execute(
            sa.text(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} "
                f"USING GIST (ST_SetSRID(ST_GeomFromGeoJSON({column}), 4326)) "
                f"WHERE {column} IS NOT NULL"
            )
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    for _table, _column, index_name in _SPATIAL_COLUMNS:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
    # The extension is intentionally left installed: other schemas may rely on it.
