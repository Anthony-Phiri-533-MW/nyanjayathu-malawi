"""Signature-Challenge validation toolkit.

Four honest, testable properties required by the assignment:

1. ``rmse``       – validate satellite-derived level/extent against gauge
                    records and report RMSE (Property 1).
2. ``units``      – unit + provenance discipline that catches metre/centimetre
                    and coordinate-system mix-ups (Property 2).
3. ``confusion``  – flood/drought risk classification from documented
                    thresholds with a confusion matrix on historical events
                    (Property 3).
4. ``cloudgap``   – cloud masking, gap interpolation and flagging so gaps are
                    never shown as observations (Property 4).

Every module is pure (no I/O, no DB) so it is fast to unit-test and can be
reused by the worker, the CLI and the API layer alike.
"""
from app.validation import cloudgap, confusion, rmse, units

__all__ = ["cloudgap", "confusion", "rmse", "units"]
