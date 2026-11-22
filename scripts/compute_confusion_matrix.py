#!/usr/bin/env python
"""Placeholder script to compute a confusion matrix for flood/drought risk classification.

Run: python scripts/compute_confusion_matrix.py
This script is referenced in the gap‑analysis for Signature‑Challenge property 3.
"""

import csv
from collections import defaultdict

BASE = pathlib.Path("data/storage")
# CSVs that would be populated from historic disaster records
indicator_file = BASE / "indicator_results" / "historic_indicators.csv"
event_file = BASE / "disaster" / "historical_events.csv"

def load_csv(path):
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

indicator_rows = load_csv(indicator_file) if indicator_file.exists() else []
event_rows = load_csv(event_file) if event_file.exists() else []

# Initialise counters
tp = fp = fn = tn = 0

for ev in event_rows:
    # expected outcome: "flood" or "drought" or None
    outcome = ev.get("outcome", "").strip().lower()
    # find matching indicator row by study_area + date (simplified)
    for ind in indicator_rows:
        # naive match: same study_area and same date string
        if ind.get("study_area") == ev.get("study_area") and ind.get("date") == ev.get("date"):
            # Determine predicted class based on threshold (simplified: if value > 475 => flood)
            try:
                value = float(ind.get("value", 0))
            except ValueError:
                value = 0.0
            # Threshold for flood: 475.0 m (example)
            predicted = "flood" if value > 475.0 else "drought"
            
            if outcome == "flood" and predicted == "flood":
                tp += 1
            elif outcome == "flood" and predicted != "flood":
                fn += 1  # missed flood
            elif outcome != "flood" and predicted == "flood":
                fp += 1  # false alarm
            else:
                tn += 1  # correct negative

print(f"Confusion Matrix:\n  True Positive: {tp}\n  False Positive: {fp}\n  False Negative: {fn}\n  True Negative: {tn}")