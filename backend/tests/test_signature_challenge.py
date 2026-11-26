"""Automated proof of the four Signature-Challenge properties.

Test IDs map to the gap analysis (SignatureGapAnalysis.md):

* TEST-V1  – Property 1: satellite level validated against gauges with RMSE.
* TEST-U1  – Property 2: unit/provenance discipline catches m/cm mix-ups.
* TEST-R1  – Property 3: threshold-driven risk classification + confusion matrix.
* TEST-C1  – Property 4: cloud gaps masked, interpolated and flagged.

The functions under test are pure, so these run in milliseconds with no DB.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from app.validation import cloudgap, confusion, rmse, units


# --------------------------------------------------------------------------- #
# Property 1 – Validation against gauge records with RMSE (TEST-V1)
# --------------------------------------------------------------------------- #
def test_rmse_matches_hand_computation():
    predicted = [10.0, 12.0, 14.0]
    observed = [10.5, 11.0, 15.0]
    # squared errors: 0.25, 1.0, 1.0 -> mean 0.75 -> sqrt = 0.8660
    assert rmse.rmse(predicted, observed) == pytest.approx(math.sqrt(0.75), rel=1e-6)


def test_rmse_rejects_length_mismatch():
    with pytest.raises(ValueError):
        rmse.rmse([1.0, 2.0], [1.0])


def test_validate_against_gauges_reports_rmse():
    gauges = [
        {"lat": -12.0, "lon": 34.5, "elevation_m": 500.0},
        {"lat": -13.0, "lon": 34.6, "elevation_m": 480.0},
    ]
    estimates = [
        {"lat": -12.01, "lon": 34.51, "value": 500.2},
        {"lat": -13.01, "lon": 34.61, "value": 479.5},
    ]
    result = rmse.validate_against_gauges(estimates, gauges)
    assert result["count"] == 2
    assert result["unit"] == "m"
    expected = math.sqrt(((500.2 - 500.0) ** 2 + (479.5 - 480.0) ** 2) / 2)
    assert result["rmse"] == pytest.approx(expected, rel=1e-3)


def test_validate_skips_far_gauges():
    gauges = [{"lat": 0.0, "lon": 0.0, "elevation_m": 1.0}]
    estimates = [{"lat": 10.0, "lon": 10.0, "value": 2.0}]
    with pytest.raises(ValueError):
        rmse.validate_against_gauges(estimates, gauges, max_distance_km=1.0)


# --------------------------------------------------------------------------- #
# Property 2 – Units and provenance (TEST-U1)
# --------------------------------------------------------------------------- #
def test_metre_centimetre_mixup_is_caught():
    # 1500 cm == 15 m, so comparing to 1500 m must be False, not True.
    assert units.compare_lengths(1500, "cm", 15, "m") is True
    assert units.compare_lengths(1500, "cm", 1500, "m") is False


def test_unknown_unit_raises():
    with pytest.raises(units.UnitMismatchError):
        units.to_metres(1.0, "furlongs")


def test_provenance_missing_field_raises():
    record = {"unit": "m", "sensor": "S2", "date": "2024-01-01"}  # no version
    with pytest.raises(units.ProvenanceError):
        units.check_provenance(record)


def test_provenance_complete_passes():
    record = {
        "unit": "m", "sensor": "S2_MPC", "date": "2024-01-01",
        "processing_version": "1.0.0", "crs": "epsg:4326",
    }
    units.check_provenance(record)  # must not raise


def test_coordinate_system_mixup_is_caught():
    with pytest.raises(units.UnitMismatchError):
        units.check_crs("epsg:32733")


# --------------------------------------------------------------------------- #
# Property 3 – Risk classification + confusion matrix (TEST-R1)
# --------------------------------------------------------------------------- #
def test_classify_uses_documented_threshold():
    threshold = {"operator": "gt", "value_low": 475.0, "direction": "flood"}
    assert confusion.classify(476.0, threshold) == "flood"
    assert confusion.classify(474.0, threshold) == "normal"


def test_confusion_matrix_counts():
    pairs = [(True, True), (True, False), (False, True), (False, False)]
    m = confusion.confusion_matrix(pairs)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert m["accuracy"] == 0.5


def test_score_events_on_history():
    threshold = {"operator": "gt", "value_low": 475.0, "direction": "flood"}
    indicators = [
        {"study_area": "south", "date": "2001-01-01", "value": 480.0},
        {"study_area": "south", "date": "2002-01-01", "value": 470.0},
    ]
    events = [
        {"study_area": "south", "date": "2001-01-01", "outcome": "flood"},
        {"study_area": "south", "date": "2002-01-01", "outcome": "none"},
    ]
    result = confusion.score_events(indicators, events, threshold)
    assert result["matched"] == 2
    assert result["tp"] == 1 and result["tn"] == 1
    assert result["accuracy"] == 1.0


# --------------------------------------------------------------------------- #
# Property 4 – Cloud gaps masked, interpolated, flagged (TEST-C1)
# --------------------------------------------------------------------------- #
def test_interpolate_fills_and_flags_gaps():
    values = np.array([[1.0, 2.0, 3.0], [4.0, np.nan, 6.0], [7.0, 8.0, 9.0]])
    valid = ~np.isnan(values)
    filled, interpolated = cloudgap.interpolate_gaps(values, valid)
    assert interpolated[1, 1] == True  # the masked cell was filled
    assert not math.isnan(filled[1, 1])
    assert filled[1, 1] == pytest.approx(5.0, rel=1e-6)  # IDW of 4 neighbours


def test_apply_cloud_gap_marks_not_observation():
    values = np.array([[10.0, 10.0], [10.0, 10.0]])
    cloud = np.array([[False, True], [False, False]])
    result = cloudgap.apply_cloud_gap(
        values, cloud, sensor="S2", processing_version="1.0.0", date="2024-01-01"
    )
    assert result["quality_flag"] == "CLOUD_CONTAMINATED"
    assert result["is_observation"] is False
    assert result["gap_interpolated_count"] == 1


def test_clear_scene_is_observation():
    values = np.array([[10.0, 11.0], [12.0, 13.0]])
    clear = np.zeros_like(values, dtype=bool)
    result = cloudgap.apply_cloud_gap(
        values, clear, sensor="S2", processing_version="1.0.0", date="2024-01-01"
    )
    assert result["quality_flag"] == "VALID"
    assert result["is_observation"] is True
    assert result["gap_interpolated_count"] == 0