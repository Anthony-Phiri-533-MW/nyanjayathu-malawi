# LakeWatch backend - FastAPI + SQLAlchemy + rasterio/geopandas.
#
# Build context is the repository root:
#   docker build -f backend/Dockerfile -t lakewatch-backend .
#
# The scientific stack (rasterio, geopandas, pyproj) ships manylinux wheels for
# CPython 3.12, so no GDAL system build is required.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# libexpat/libsqlite are pulled in by the wheels; curl is used for the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer: copied alone so code edits do not reinstall the stack.
COPY backend/pyproject.toml ./
RUN uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python \
        fastapi "uvicorn[standard]" "pydantic>=2.9" pydantic-settings email-validator \
        "sqlalchemy>=2.0.35" alembic "psycopg[binary]" pyjwt bcrypt httpx python-multipart \
        numpy pandas xarray h5netcdf h5py rasterio geopandas shapely pyproj affine reportlab

# Application layer.
COPY backend/ ./

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/health" || exit 1

# Migrations are applied by the entrypoint so a fresh database is usable
# immediately; AUTO_CREATE_TABLES/STARTUP_BOOTSTRAP cover a dev database.
# Render and Railway inject PORT, so bind to it when present and fall back to
# 8000 for Docker Compose and local runs.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
