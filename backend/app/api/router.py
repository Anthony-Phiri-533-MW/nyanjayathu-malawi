"""Aggregate the versioned API router."""
from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    analysis,
    assistant,
    audit,
    auth,
    data_sources,
    datasets,
    disaster,
    exports,
    forecasting,
    indicators,
    ingestion,
    jobs,
    processing,
    providers,
    public,
    reports,
    scheduler,
    study_areas,
    thresholds,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(data_sources.router)
api_router.include_router(thresholds.router)
api_router.include_router(audit.router)
api_router.include_router(providers.router)
api_router.include_router(study_areas.router)
api_router.include_router(datasets.router)
api_router.include_router(jobs.router)
api_router.include_router(ingestion.router)
api_router.include_router(processing.router)
api_router.include_router(indicators.router)
api_router.include_router(analysis.router)
api_router.include_router(assistant.router)
api_router.include_router(exports.router)
api_router.include_router(disaster.router)
api_router.include_router(forecasting.router)
api_router.include_router(scheduler.router)
api_router.include_router(reports.router)
api_router.include_router(public.router)
