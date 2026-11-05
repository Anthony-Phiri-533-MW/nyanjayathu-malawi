"""Import side-effects registering every background job handler.

Import this module once at application startup (``app.main``) so the worker can
resolve every supported background job kind.
"""
from app.services import exports, forecasting, indicators, ingestion, pipeline, processing, reports  # noqa: F401

__all__ = ["exports", "forecasting", "indicators", "ingestion", "pipeline", "processing", "reports"]
