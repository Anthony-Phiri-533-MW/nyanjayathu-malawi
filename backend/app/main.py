"""LakeWatch FastAPI application.

Startup order: storage directories -> (dev) metadata.create_all -> idempotent
bootstrap (roles/permissions, default study area, indicator definitions) ->
background job workers.  In production set ``AUTO_CREATE_TABLES=false`` and
run ``alembic upgrade head`` instead of the create_all step.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import settings
from app.core.database import engine, session_scope
from app.core.errors import install_error_handlers
from app.models import Base
from app.providers import close_http_client
from app.services import handlers  # noqa: F401  (registers job handlers)
from app.services.bootstrap import run_bootstrap
from app.services.jobs import start_workers, stop_workers
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.storage import ensure_storage_dirs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("lakewatch")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_storage_dirs()
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
    if settings.startup_bootstrap:
        with session_scope() as db:
            try:
                run_bootstrap(db)
            except Exception:
                log.exception("Bootstrap failed")
                raise
    if settings.jobs_enabled:
        start_workers()
    start_scheduler()
    log.info("LakeWatch API ready (environment=%s)", settings.environment)
    try:
        yield
    finally:
        stop_scheduler()
        stop_workers()
        close_http_client()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Admin and Data Analysis & Research modules for a Lake Malawi "
        "satellite water-level / water-quality monitoring system."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

install_error_handlers(app)
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
def health() -> dict:
    database = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        database = f"error: {type(exc).__name__}"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "environment": settings.environment,
        "database": database,
        "jobs_enabled": settings.jobs_enabled,
        "version": app.version,
    }


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"name": settings.app_name, "docs": "/docs", "api": "/api/v1"}
