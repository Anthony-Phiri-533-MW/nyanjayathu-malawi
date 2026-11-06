"""Provider catalogue: list, detail and schema catalogue."""
from __future__ import annotations

import json
from datetime import date

import httpx
from fastapi.testclient import TestClient

from app.providers.base import IngestParams, ProviderError
from app.providers.chirps import ChirpsAdapter
from app.providers.nasa_power import DEFAULT_PARAMETERS, NasaPowerAdapter
from app.providers.planetary_computer import (
    ModisLstMpc,
    ModisMpc,
    LandsatMpc,
    Sentinel2Mpc,
    Sentinel3SralMpc,
)
from app.providers.raster import download_file


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


def test_planetary_computer_assets_match_current_stac_products() -> None:
    assert LandsatMpc.default_assets == ["blue", "green", "red", "nir08", "swir16", "swir22", "lwir11"]
    assert "qa_pixel" in LandsatMpc.asset_rules
    assert ModisMpc.qa_assets == ["sur_refl_state_500m"]
    assert "sur_refl_state_500m" in ModisMpc.asset_rules
    assert ModisLstMpc.default_assets == ["LST_Day_1km"]
    assert ModisLstMpc.qa_assets == ["QC_Day"]
    assert "LST_Day_1km" in ModisLstMpc.asset_rules
    assert Sentinel3SralMpc.default_assets == ["standard-measurement"]
    assert LandsatMpc.asset_aliases["SR_B3"] == "green"
    assert LandsatMpc.asset_aliases["ST_B10"] == "lwir11"
    assert ModisLstMpc.asset_aliases["LST_1km"] == "LST_Day_1km"
    assert Sentinel3SralMpc.asset_aliases["wat_meas"] == "standard-measurement"


def test_planetary_computer_fetch_resolves_legacy_asset_names(monkeypatch, tmp_path) -> None:
    from app.providers.base import DiscoveredItem

    item = DiscoveredItem(
        asset_id="scene-1",
        title="Scene 1",
        start_date=date(2026, 8, 15),
        end_date=date(2026, 8, 15),
        assets={"green": "https://assets.test/green.tif", "qa_pixel": "https://assets.test/qa.tif"},
    )
    adapter = LandsatMpc(config={})
    monkeypatch.setattr(adapter, "sign_href", lambda href: href)

    def fake_fetch(_source, dest, *, native_name, **_kwargs):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"raster")
        return {
            "crs": "EPSG:4326",
            "resolution_m": 30,
            "bounds_wgs84": [34, -12, 35, -11],
            "shape": [1, 1],
            "unit": "reflectance",
        }

    from app.providers import planetary_computer as mpc

    monkeypatch.setattr(mpc, "fetch_raster_band", fake_fetch)
    monkeypatch.setattr(mpc, "_combined_checksum", lambda _files: "checksum")
    monkeypatch.setattr(mpc, "_is_raster_suffix", lambda _suffix: True)
    monkeypatch.setattr(mpc, "_asset_suffix", lambda _href, _key: ".tif")
    monkeypatch.setattr(mpc, "_slug", lambda value: value)
    monkeypatch.setattr("app.services.storage.relative", lambda path: str(path))

    artifact = adapter.fetch(
        IngestParams(
            bbox=(34, -12, 35, -11),
            start_date=date(2026, 8, 15),
            end_date=date(2026, 8, 15),
            variables=["SR_B3"],
            dest_dir=tmp_path,
        ),
        item,
    )

    assert artifact.variables == ["green", "qa_pixel"]
    assert set(artifact.metadata["bands"]) == {"green", "qa_pixel"}
    assert set(artifact.metadata["granules"][0]["bands"]) == {"green", "qa_pixel"}


def test_planetary_computer_stac_search_follows_pages_and_reports_limit() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        if '"token":"page-2"' in body:
            return httpx.Response(200, json={"features": [{"id": "second"}], "links": []})
        return httpx.Response(
            200,
            json={
                "features": [{"id": "first"}],
                "links": [
                    {
                        "rel": "next",
                        "href": "https://stac.test/search",
                        "method": "POST",
                        "body": {"token": "page-2"},
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        adapter = Sentinel2Mpc(client=client, config={"stac_url": "https://stac.test"})
        features = adapter._search({"limit": 1}, max_items=2)
        assert [feature["id"] for feature in features] == ["first", "second"]

        try:
            adapter._search({"limit": 1}, max_items=1)
        except ProviderError as exc:
            assert "configured ingestion limit" in str(exc)
        else:
            raise AssertionError("Expected paged results beyond the configured cap to fail")


def test_planetary_computer_discovery_uses_study_area_geometry() -> None:
    study_area = {
        "type": "Polygon",
        "coordinates": [[[34.0, -12.0], [35.0, -12.0], [35.0, -11.0], [34.0, -11.0], [34.0, -12.0]]],
    }
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "features": [{
                    "id": "scene-1",
                    "bbox": [34.0, -12.0, 35.0, -11.0],
                    "properties": {"datetime": "2026-08-15T00:00:00Z"},
                    "assets": {"green": {"href": "https://assets.test/green.tif"}},
                }],
                "links": [],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        adapter = LandsatMpc(client=client, config={"stac_url": "https://stac.test"})
        items = adapter.discover(
            IngestParams(
                bbox=(33.8, -14.5, 35.3, -9.4),
                start_date=date(2026, 8, 15),
                end_date=date(2026, 8, 15),
                extra={"intersects": study_area},
            )
        )

    body = json.loads(requests[0].content)
    assert body["intersects"] == study_area
    assert "bbox" not in body
    assert len(items) == 1


def test_chirps_discovery_fails_instead_of_silently_truncating_date_range() -> None:
    adapter = ChirpsAdapter(config={})
    params = IngestParams(
        bbox=(33.8, -14.5, 35.3, -9.4),
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 3),
        max_items=2,
    )

    try:
        adapter.discover(params)
    except ProviderError as exc:
        assert "configured item limit" in str(exc)
    else:
        raise AssertionError("Expected a capped CHIRPS range to fail explicitly")


def test_download_errors_redact_signed_url_query(tmp_path) -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    url = "https://data.example/asset.tif?sig=private-signature"
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        try:
            download_file(client, url, dest=tmp_path / "asset.tif")
        except ProviderError as exc:
            message = str(exc)
        else:
            raise AssertionError("Expected the denied asset request to raise ProviderError")

    assert "private-signature" not in message
    assert "sig=" not in message
    assert "[redacted]" in message
