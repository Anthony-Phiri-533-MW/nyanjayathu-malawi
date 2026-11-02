"""Import side-effects registering every background job handler.

Import this module once at application startup (``app.main``) so the worker can
resolve every supported background job kind.
"""
from app.services import exports, indicators, ingestion, processing, reports  # noqa: F401

__all__ = ["exports", "indicators", "ingestion", "processing", "reports"]
