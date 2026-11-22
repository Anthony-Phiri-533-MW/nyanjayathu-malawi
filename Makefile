.PHONY: test lint seed validate confusion interpolate

test:
	cd backend && python -m pytest

lint:
	cd backend && uvx ruff check .

seed:
	python scripts/seed_gauges.py

validate:
	python scripts/validate_gauges.py

confusion:
	python scripts/compute_confusion_matrix.py

interpolate:
	python scripts/interpolate_cloud_gaps.py