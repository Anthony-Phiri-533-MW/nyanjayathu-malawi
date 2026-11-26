#!/usr/bin/env python
"""Live demonstration of the four Signature-Challenge properties.

Run from the backend directory with the project venv::

    python ../scripts/signature_demo.py

It exercises the pure ``app.validation`` modules and prints the evidence a
demonstrator can read out: RMSE against gauges, a metre/centimetre mix-up that
is caught, a risk confusion matrix on historical events, and a cloud-gap that
is interpolated and flagged (never shown as an observation).
"""
from __future__ import annotations

import sys
import numpy as np

sys.path.insert(0, ".")

from app.validation import cloudgap, confusion, rmse, units  # noqa: E402


def demo_validation() -> None:
    gauges = [{"lat": -12.0, "lon": 34.5, "elevation_m": 500.0}]
    estimates = [{"lat": -12.01, "lon": 34.51, "value": 500.3}]
    result = rmse.validate_against_gauges(estimates, gauges)
    print("[P1] gauge validation ->", result)


def demo_units() -> None:
    caught = not units.compare_lengths(1500, "cm", 1500, "m")
    print(f"[P2] 1500 cm vs 1500 m equal? {not caught} (mix-up caught = {caught})")


def demo_risk() -> None:
    threshold = {"operator": "gt", "value_low": 475.0, "direction": "flood"}
    indicators = [{"study_area": "south", "date": "2001-01-01", "value": 480.0}]
    events = [{"study_area": "south", "date": "2001-01-01", "outcome": "flood"}]
    print("[P3] risk confusion matrix ->", confusion.score_events(indicators, events, threshold))


def demo_cloudgap() -> None:
    values = np.array([[10.0, np.nan], [10.0, 10.0]])
    cloud = np.isnan(values)
    result = cloudgap.apply_cloud_gap(
        values, cloud, sensor="S2", processing_version="1.0.0", date="2024-01-01"
    )
    print(f"[P4] cloud gap -> flag={result['quality_flag']} "
          f"observation={result['is_observation']} filled={result['gap_interpolated_count']}")


if __name__ == "__main__":
    demo_validation()
    demo_units()
    demo_risk()
    demo_cloudgap()