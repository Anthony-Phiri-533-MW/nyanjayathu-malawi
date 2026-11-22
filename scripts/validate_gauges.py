#!/usr/bin/env python
"""Placeholder script to validate indicator values against gauge records and compute RMSE.

Run: python scripts/validate_gauges.py
This script is referenced in the gap‑analysis for Signature‑Challenge property 1.
"""

import csv
import math
import pathlib
from statistics import mean

BASE = pathlib.Path("data/storage")
gauge_file = BASE / "gauges" / "malawi_gauges.csv"
# Suppose we have a results CSV produced by the processing pipeline
results_file = BASE / "indicator_results" / "water_level_altitude.csv"

def load_csv(path):
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

gauge_rows = load_csv(gauge_file) if gauge_file.exists() else []
result_rows = load_csv(results_file) if results_file.exists() else []

# Dummy RMSE computation – in a real implementation we would match nearest gauge
# to each indicator pixel and compute sqrt(mean((value - gauge)²)).
if result_rows and gauge_rows:
    differences = []
    for r in result_rows:
        try:
            val = float(r.get("value", 0))
        except ValueError:
            val = 0.0
        # pick first gauge as stand‑in
        gauge_val = float(gauge_rows[0].get("elevation_m", 0))
        differences.append(val - gauge_val)
    rmse = math.sqrt(mean([d**2 for d in differences]))
    print(f"Computed RMSE against gauges: {rmse:.3f} m")
else:
    print("Not enough data to compute RMSE – add gauge and indicator CSVs.")