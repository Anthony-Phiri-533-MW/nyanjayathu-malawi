"""Published dashboard map layers, water-mask polygons and assistant responses."""
from __future__ import annotations

import json
from datetime import date

import httpx
import numpy as np
from fastapi.testclient import TestClient
from rasterio.crs import CRS
from rasterio.transform import Affine

from app.core.config import settings
from app.core.database import session_scope
from app.indicators.water import _water_extent_geometry
from app.models import Dataset, IndicatorDefinition, IndicatorResult
from app.processing.io import RasterRead
from app.services import assistant as assistant_service

_WATER_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [34.1, -12.1],
        [34.2, -12.1],
        [34.2, -12.2],
        [34.1, -12.2],
        [34.1, -12.1],
    ]],
}


def test_water_extent_geometry_tracks_classified_pixels() -> None:
    ref = RasterRead(
        data=np.ones((1, 5, 5), dtype="float32"),
        band_names=["green"],
        crs=CRS.from_epsg(4326),
        transform=Affine(0.01, 0, 34, 0, -0.01, -12),
        nodata=None,
        valid_mask=np.ones((5, 5), dtype=bool),
        bounds=(34, -12.05, 34.05, -12),
    )
    mask = np.zeros((5, 5), dtype=bool)
    mask[1:4, 1:4] = True

    geometry = _water_extent_geometry(mask, ref)

    assert geometry is not None
    assert geometry["type"] in {"Polygon", "MultiPolygon"}
    coordinates = geometry["coordinates"]
    if geometry["type"] == "Polygon":
        coordinates = [coordinates]
    points = [point for polygon in coordinates for ring in polygon for point in ring]
    assert min(point[0] for point in points) >= 34.009
    assert max(point[0] for point in points) <= 34.041
    assert min(point[1] for point in points) >= -12.041
    assert max(point[1] for point in points) <= -12.009


def test_public_dashboard_only_returns_published_spatial_data(
    client: TestClient,
    admin_headers: dict[str, str],
    default_study_area: dict,
) -> None:
    with session_scope() as db:
        definition = db.query(IndicatorDefinition).filter_by(key="water_extent").one()
        dataset = Dataset(
            title="Dashboard map publication probe",
            provider_key="test_provider",
            category="satellite",
            product_type="demo",
            kind="observed",
            is_raw=True,
            study_area_id=default_study_area["id"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 1),
            coverage_geojson=_WATER_GEOMETRY,
            quality_flag="VALID",
        )
        db.add(dataset)
        db.flush()
        dataset_id = dataset.id
        db.add(
            IndicatorResult(
                definition_id=definition.id,
                indicator_key="water_extent",
                study_area_id=default_study_area["id"],
                dataset_id=dataset_id,
                value=1234.5,
                unit="km²",
                observed_start=date(2026, 1, 1),
                observed_end=date(2026, 1, 1),
                quality_flag="VALID",
                quality_reason="test observation",
                spatial_extent_geojson=_WATER_GEOMETRY,
            )
        )

    private_frames = client.get("/api/v1/public/water-extents").json()["items"]
    assert all(frame["dataset_id"] != dataset_id for frame in private_frames)
    private_coverages = client.get("/api/v1/public/map").json()["dataset_coverages"]
    assert all(feature["id"] != dataset_id for feature in private_coverages)
    private_indicators = client.get("/api/v1/public/map").json()["indicator_observations"]
    assert all(
        feature["properties"]["dataset_title"] != "Dashboard map publication probe"
        for feature in private_indicators
    )

    published = client.patch(
        f"/api/v1/public/datasets/{dataset_id}",
        json={"is_public": True},
        headers=admin_headers,
    )
    assert published.status_code == 200, published.text

    frames = client.get("/api/v1/public/water-extents").json()["items"]
    frame = next(row for row in frames if row["dataset_id"] == dataset_id)
    assert frame["value"] == 1234.5
    assert frame["spatial_extent_geojson"] == _WATER_GEOMETRY

    coverages = client.get("/api/v1/public/map").json()["dataset_coverages"]
    coverage = next(feature for feature in coverages if feature["id"] == dataset_id)
    assert coverage["geometry"] == _WATER_GEOMETRY
    observations = client.get("/api/v1/public/map").json()["indicator_observations"]
    observation = next(
        feature for feature in observations if feature["properties"]["id"]
        == frame["id"]
    )
    assert observation["properties"]["indicator_key"] == "water_extent"
    assert observation["properties"]["value"] == 1234.5
    assert observation["geometry"] == _WATER_GEOMETRY
    published_area = client.patch(
        f"/api/v1/public/study-areas/{default_study_area['id']}",
        json={"is_public": True},
        headers=admin_headers,
    )
    assert published_area.status_code == 200, published_area.text
    public_area = next(
        feature
        for feature in client.get("/api/v1/public/map").json()["features"]
        if feature["id"] == default_study_area["id"]
    )
    assert public_area["properties"]["is_default"] is True
    assert public_area["geometry"] == default_study_area["boundary_geojson"]
    unpublished = client.patch(
        f"/api/v1/public/datasets/{dataset_id}",
        json={"is_public": False},
        headers=admin_headers,
    )
    assert unpublished.status_code == 200, unpublished.text


def test_assistant_requires_auth_and_reports_unconfigured_provider(
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "ai_base_url", None)
    monkeypatch.setattr(settings, "ai_model", None)
    payload = {"question": "What does this mean?", "metrics": []}

    assert client.post("/api/v1/assistant/interpret", json=payload).status_code == 401
    response = client.post(
        "/api/v1/assistant/interpret",
        json=payload,
        headers=admin_headers,
    )
    assert response.status_code == 503
    assert "AI_BASE_URL" in response.json()["error"]["message"]


def test_assistant_sends_only_context_to_configured_provider(
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "ai_base_url", "https://ai.example.test/v1")
    monkeypatch.setattr(settings, "ai_model", "lakewatch-test")
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Water extent is mapped surface area."}}]},
        )

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        assistant_service.httpx,
        "AsyncClient",
        lambda **kwargs: real_async_client(
            transport=httpx.MockTransport(handle),
            **kwargs,
        ),
    )

    response = client.post(
        "/api/v1/assistant/interpret",
        json={
            "question": "What does water extent mean?",
            "metrics": [{"label": "Mapped water extent", "value": "1234 km²"}],
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["answer"] == "Water extent is mapped surface area."
    assert seen["url"] == "https://ai.example.test/v1/chat/completions"
    assert seen["authorization"] == "Bearer test-key"
    assert seen["body"]["model"] == "lakewatch-test"
    assert seen["body"]["messages"][1]["content"].find("1234 km²") >= 0
