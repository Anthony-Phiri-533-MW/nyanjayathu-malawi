from __future__ import annotations

import numpy as np
import pytest

from app.core.errors import UnprocessableError
from app.services import local_models


class _FakeTurbidityModel:
    def predict(self, frame):
        assert list(frame.columns) == [
            "air_temp_c",
            "precipitation_mm",
            "wind_speed_m_s",
            "solar_radiation_wm2",
        ]
        assert frame.shape == (1, 4)
        return np.array([4.25])


def test_local_model_catalog_exposes_documented_feature_schemas():
    models = {model["key"]: model for model in local_models.list_local_models()}

    assert set(models) == {"turbidity", "surface_temperature", "water_extent"}
    assert [feature["key"] for feature in models["turbidity"]["features"]] == [
        "air_temp_c",
        "precipitation_mm",
        "wind_speed_m_s",
        "solar_radiation_wm2",
    ]
    assert len(models["surface_temperature"]["features"]) == 16
    assert len(models["water_extent"]["features"]) == 10


def test_local_model_prediction_uses_named_turbidity_features(monkeypatch):
    monkeypatch.setattr(local_models, "_load_model", lambda _key: _FakeTurbidityModel())
    features = {
        "air_temp_c": 25.5,
        "precipitation_mm": 2.3,
        "wind_speed_m_s": 4.1,
        "solar_radiation_wm2": 18.5,
    }

    prediction = local_models.predict_local_model("turbidity", features)

    assert prediction["value"] == pytest.approx(4.25)
    assert prediction["unit"] == "NTU"
    assert prediction["features"] == features


def test_local_model_prediction_rejects_missing_features():
    with pytest.raises(UnprocessableError, match="exactly match"):
        local_models.predict_local_model("turbidity", {"air_temp_c": 25.5})


def test_local_model_catalog_api(client, admin_headers):
    response = client.get("/api/v1/forecasts/local-models", headers=admin_headers)

    assert response.status_code == 200
    assert {model["key"] for model in response.json()} == {
        "turbidity",
        "surface_temperature",
        "water_extent",
    }


def test_local_model_prediction_api_allows_researcher(client, make_user, monkeypatch):
    _, researcher_headers = make_user("local-model-researcher@example.org")
    monkeypatch.setattr(
        "app.api.forecasting.local_models.predict_local_model",
        lambda key, features: {
            "model_key": key,
            "model_name": "Test local model",
            "target": "Test target",
            "unit": "test",
            "value": 2.5,
            "features": features,
        },
    )

    response = client.post(
        "/api/v1/forecasts/local-models/turbidity/predict",
        json={"features": {"air_temp_c": 22.0}},
        headers=researcher_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["value"] == pytest.approx(2.5)


def test_local_model_prediction_api_requires_authentication(client):
    response = client.post(
        "/api/v1/forecasts/local-models/turbidity/predict",
        json={"features": {}},
    )

    assert response.status_code == 401
