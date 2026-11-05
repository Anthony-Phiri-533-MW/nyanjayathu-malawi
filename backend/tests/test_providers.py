"""Provider catalogue: list, detail and schema catalogue."""
from __future__ import annotations

from fastapi.testclient import TestClient


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
