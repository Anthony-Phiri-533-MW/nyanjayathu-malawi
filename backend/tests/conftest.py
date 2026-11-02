"""Shared pytest fixtures.

The suite never touches the network: provider HTTP is replaced with an
``httpx.MockTransport`` and background workers stay off.  Each test session
gets its own SQLite file and storage root so runs are independent.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# --- environment must be set *before* app modules import settings ----------
_TMP = Path(tempfile.mkdtemp(prefix="lakewatch_tests_"))
_DB_PATH = _TMP / "test.db"
_STORAGE = _TMP / "storage"

os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["STORAGE_ROOT"] = str(_STORAGE)
os.environ["JOBS_ENABLED"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-0123456789abcdef"

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

from app.cli import _bootstrap_admin  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.processing.io import write_geotiff  # noqa: E402

ADMIN_EMAIL = "admin@example.org"
ADMIN_PASSWORD = "Sup3r-secret-pass"

# A small square fully inside the default Lake Malawi study area bbox.
AOI = {
    "type": "Polygon",
    "coordinates": [
        [
            [34.2, -12.7],
            [34.6, -12.7],
            [34.6, -12.3],
            [34.2, -12.3],
            [34.2, -12.7],
        ]
    ],
}


@pytest.fixture(scope="session")
def client() -> TestClient:
    _bootstrap_admin(ADMIN_EMAIL, ADMIN_PASSWORD, "Test Admin")
    with TestClient(app) as test_client:
        yield test_client
    from app.providers.base import close_http_client

    close_http_client()


@pytest.fixture(scope="session")
def admin_token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


# --------------------------------------------------------------- helpers
@pytest.fixture
def make_user(client: TestClient, admin_headers: dict[str, str]):
    """Create a user and return (user_dict, auth_headers)."""

    created: list[int] = []

    def _factory(
        email: str,
        role: str = "researcher",
        password: str = "Sup3r-secret-pass",
        full_name: str = "Test User",
    ) -> tuple[dict, dict[str, str]]:
        response = client.post(
            "/api/v1/admin/users",
            json={
                "email": email,
                "full_name": full_name,
                "password": password,
                "roles": [role],
            },
            headers=admin_headers,
        )
        assert response.status_code == 201, response.text
        user = response.json()
        created.append(user["id"])
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        return user, headers

    yield _factory

    # No user-delete endpoint exists (accounts are soft-deactivated for audit
    # integrity), so cleanup is limited to deactivating what we created.
    for user_id in created:
        client.post(f"/api/v1/admin/users/{user_id}/deactivate", headers=admin_headers)


@pytest.fixture
def default_study_area(client: TestClient, admin_headers: dict[str, str]) -> dict:
    response = client.get("/api/v1/study-areas", headers=admin_headers)
    assert response.status_code == 200, response.text
    items = response.json()
    assert items, "bootstrap should create a default study area"
    return next((a for a in items if a.get("is_default")), items[0])


@pytest.fixture
def synthetic_geotiff():
    """Factory writing a synthetic multi-band GeoTIFF inside the AOI.

    ``bands`` maps band name -> array.  Returns the absolute file path plus
    the transform used, so callers can register a Dataset pointing at it.
    """

    def _factory(
        directory: Path,
        bands: dict[str, np.ndarray],
        *,
        transform=None,
        crs: str = "EPSG:4326",
        nodata: float = -9999.0,
    ) -> tuple[Path, object]:
        names = list(bands)
        stack = np.stack([np.asarray(bands[name], dtype="float32") for name in names])
        if transform is None:
            transform = from_origin(34.2, -12.3, 0.01, 0.01)
        path = Path(directory) / "synthetic.tif"
        write_geotiff(
            path,
            stack,
            transform=transform,
            crs=crs,
            nodata=nodata,
            band_names=names,
        )
        return path, transform

    return _factory


def read_raster(path: Path) -> tuple[np.ndarray, dict]:
    with rasterio.open(path) as src:
        return src.read(), {"transform": src.transform, "crs": src.crs, "count": src.count}


@pytest.fixture
def storage_root() -> Path:
    return Path(settings.storage_root)
