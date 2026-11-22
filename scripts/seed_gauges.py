#!/usr/bin/env python
"""Placeholder script to seed Malawi gauge station data.

Run: python scripts/seed_gauges.py
This script creates sample gauge CSV rows that can be ingested
by the malawi_gauges provider (see ADR‑04).
"""

import csv
import pathlib

BASE = pathlib.Path("data/storage")
gauge_dir = BASE / "gauges"
gauge_dir.mkdir(parents=True, exist_ok=True)

rows = [
    {"station": "Likoma", "lat": "-12.0333", "lon": "34.7500", "elevation_m": "500"},
    {"station": "Monkey Bay", "lat": "-13.9667", "lon": "34.5667", "elevation_m": "480"},
    {"station": "Nkhotakota", "lat": "-13.6000", "lon": "34.4333", "elevation_m": "470"},
]

with open(gauge_dir / "malawi_gauges.csv", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["station", "lat", "lon", "elevation_m"])
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

print(f" seeded {gauge_dir / 'malawi_gauges.csv'}")