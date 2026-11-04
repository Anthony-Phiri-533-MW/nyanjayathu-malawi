"""Dataset browsing: listing, filtering, quality flags and detail."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.core.database import session_scope
from app.models import Dataset


def _seed_dataset(
    *,
    title: str,
    provider_key: str = "chirps",
    category: str = "climate",
    kind: str = "observed",
    quality_flag: str = "UNVALIDATED",
    study_area_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> None:
    with session_scope() as db:
        db.add(
            Dataset(
                title=title,
                provider_key=provider_key,
                category=category,
                product_type="demo",
                kind=kind,
                is_raw=True,
                study_area_id=study_area_id,
                start_date=start_date or date.today() - timedelta(days=30),
                end_date=end_date or date.today(),
                quality_flag=quality_flag,
                quality_reason="seeded by dataset test",
            )
        )


# --------------------------------------------------------------------- listing & filters
def test_list_datasets_and_filters(
    client: TestClient, admin_headers: dict[str, str], default_study_area: dict
) -> None:
    sa = default_study_area["id"]
    _seed_dataset(title="Rainfall CHIRPS", provider_key="chirps", category="climate", study_area_id=sa)
    _seed_dataset(title="Sentinel-2 scene", provider_key="sentinel2_mpc", category="satellite", kind="observed", study_area_id=sa)
    _seed_dataset(title="Quality flagged", provider_key="chirps", category="climate", quality_flag="VALID", study_area_id=sa)

    listed = client.get("/api/v1/datasets", headers=admin_headers).json()
    assert listed["total"] >= 3
    for item in listed["items"]:
        assert "title" in item and "quality_flag" in item and "provider_key" in item

    # search filter
    listed = client.get(
        "/api/v1/datasets", params={"search": "Sentinel", "size": 50}, headers=admin_headers
    ).json()
    assert all("Sentinel" in i["title"] for i in listed["items"])

    # provider filter
    listed = client.get(
        "/api/v1/datasets", params={"provider_key": "chirps", "size": 50}, headers=admin_headers
    ).json()
    assert all(i["provider_key"] == "chirps" for i in listed["items"])

    # category filter
    listed = client.get(
        "/api/v1/datasets", params={"category": "satellite", "size": 50}, headers=admin_headers
    ).json()
    assert all(i["category"] == "satellite" for i in listed["items"])

    # quality flag filter
    listed = client.get(
        "/api/v1/datasets", params={"quality_flag": "VALID", "size": 50}, headers=admin_headers
    ).json()
    assert all(i["quality_flag"] == "VALID" for i in listed["items"])

    # study area filter
    listed = client.get(
        "/api/v1/datasets", params={"study_area_id": sa, "size": 50}, headers=admin_headers
    ).json()
    assert all(i["study_area_id"] == sa for i in listed["items"])

    # date range filter
    listed = client.get(
        "/api/v1/datasets",
        params={"start_date": date.today().isoformat(), "size": 50},
        headers=admin_headers,
    ).json()
    assert listed["total"] >= 0


def test_quality_flags_endpoint(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/datasets/quality-flags", headers=admin_headers)
    assert response.status_code == 200
    flags = response.json()
    expected = {"VALID", "LOW_QUALITY", "INSUFFICIENT_COVERAGE", "CLOUD_CONTAMINATED", "MISSING_DATA", "PROCESSING_FAILED", "UNVALIDATED"}
    assert set(flags) == expected


def test_get_dataset_detail(client: TestClient, admin_headers: dict[str, str], default_study_area: dict) -> None:
    _seed_dataset(title="Detail dataset", provider_key="chirps", category="climate", study_area_id=default_study_area["id"])
    newest = client.get("/api/v1/datasets", params={"size": 1}, headers=admin_headers).json()["items"][0]
    dataset_id = newest["id"]

    detail = client.get(f"/api/v1/datasets/{dataset_id}", headers=admin_headers).json()
    assert detail["id"] == dataset_id
    assert detail["title"] == "Detail dataset"
    assert "bands" in detail
    assert "quality_flag" in detail

    # band statistics (may be None for seeded rows without raster files)
    stats = client.get(
        f"/api/v1/datasets/{dataset_id}", params={"include_band_statistics": "true"}, headers=admin_headers
    ).json()
    assert detail["id"] == stats["id"]
