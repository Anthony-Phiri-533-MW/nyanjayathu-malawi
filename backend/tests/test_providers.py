"""Provider catalogue: list, detail and schema catalogue."""
from __future__ import annotations

from datetime import date

import httpx
from fastapi.testclient import TestClient

from app.providers.base import IngestParams
from app.providers.nasa_power import DEFAULT_PARAMETERS, NasaPowerAdapter


def test_list_providers(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/providers", headers=admin_headers)
    assert response.status_code == 200
    providers = response.json()
    assert len(providers) == 7
    keys = {p["key"] for p in providers}
    assert keys == {
        "sentinel2_mpc", "landsat_mpc", "modis_mpc", "modis_lst_mpc",
        "sentinel3_sral", "chirps", "nasa_power",
    }
    for provider in providers:
        for field in ("key", "label", "category", "description", "product_type",
                      "verification_note", "auth_method", "auth_required",
                      "variables", "capabilities", "adapter_status"):
            assert field in provider, provider


def test_get_provider(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/providers/chirps", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "chirps"
    assert body["label"] == "CHIRPS v2.0 daily rainfall"
    assert body["auth_required"] is False

    response = client.get("/api/v1/providers/no_such_provider", headers=admin_headers)
    assert response.status_code == 404


def test_catalogue(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/providers/catalogue", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert "categories" in body
    assert "auth_methods" in body
    assert len(body["categories"]) >= 1
    assert len(body["auth_methods"]) >= 1
    for entry in body["categories"]:
        assert "value" in entry and "label" in entry
    for entry in body["auth_methods"]:
        assert "value" in entry and "label" in entry


def test_nasa_power_daily_point_ingestion_uses_configured_api_parameters(tmp_path, monkeypatch) -> None:
    expected_parameters = ["T2M", "PRECTOTCORR", "WS2M", "ALLSKY_SFC_SW_DWN"]
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        values = {key: {"20220101": 1.5, "20220102": -999.0} for key in expected_parameters}
        return httpx.Response(
            200,
            json={
                "header": {"fill_value": -999.0, "api": {"version": "v2"}},
                "parameters": {key: {"units": "unit", "longname": key} for key in expected_parameters},
                "properties": {"parameter": values},
            },
        )

    from app.services import storage

    monkeypatch.setattr(storage, "relative", lambda path: path.name)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        adapter = NasaPowerAdapter(client=client, config={"base_url": "https://power.test/api"})
        params = IngestParams(
            bbox=(34.5, -13.0, 35.5, -12.0),
            start_date=date(2022, 1, 1),
            end_date=date(2022, 1, 2),
            dest_dir=tmp_path,
        )
        item = adapter.discover(params)[0]
        artifact = adapter.fetch(params, item)

    request = requests[0]
    assert str(request.url).startswith("https://power.test/api/temporal/daily/point?")
    assert request.url.params["parameters"] == ",".join(DEFAULT_PARAMETERS)
    assert request.url.params["community"] == "AG"
    assert request.url.params["longitude"] == "35.0"
    assert request.url.params["latitude"] == "-12.5"
    assert request.url.params["start"] == "20220101"
    assert request.url.params["end"] == "20220102"
    assert request.url.params["format"] == "JSON"
    assert artifact.variables == expected_parameters
    csv_path = next(tmp_path.glob("*.csv"))
    assert csv_path.read_text(encoding="utf-8").splitlines() == [
        "date,T2M,PRECTOTCORR,WS2M,ALLSKY_SFC_SW_DWN",
        "2022-01-01,1.5,1.5,1.5,1.5",
        "2022-01-02,,,,",
    ]
