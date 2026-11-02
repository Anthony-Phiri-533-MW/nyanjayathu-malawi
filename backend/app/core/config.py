"""Application configuration loaded from environment variables (.env supported)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LakeWatch API"
    environment: str = Field(default="development")

    # --- database ---------------------------------------------------------
    # PostgreSQL+PostGIS is the primary target (see docker-compose.yml).
    # SQLite is supported as a zero-configuration fallback for local
    # development and the automated test suite.
    database_url: str = f"sqlite:///{BASE_DIR / 'dev.db'}"
    # Development convenience: create missing tables and seed required rows on
    # startup.  Set to false in production and run `alembic upgrade head`.
    auto_create_tables: bool = True
    startup_bootstrap: bool = True

    # --- security ---------------------------------------------------------
    secret_key: str = "insecure-dev-secret-change-me-in-production"
    access_token_expire_minutes: int = 480
    bcrypt_rounds: int = 12

    # --- bootstrap administrator (used by `python -m app.cli bootstrap-admin`)
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_admin_name: str | None = None

    # --- storage ----------------------------------------------------------
    storage_root: Path = BASE_DIR.parent / "data" / "storage"

    # --- background jobs --------------------------------------------------
    jobs_enabled: bool = True
    jobs_poll_interval_seconds: float = 2.0
    jobs_worker_count: int = 2
    jobs_max_attempts: int = 3

    # --- HTTP / providers -------------------------------------------------
    http_timeout_seconds: float = 30.0
    chirps_base_url: str = "https://data.chc.ucsb.edu/products/CHIRPS-2.0"
    nasa_power_base_url: str = "https://power.larc.nasa.gov/api"
    planetary_computer_stac_url: str = "https://planetarycomputer.microsoft.com/api/stac/v1"
    planetary_computer_sas_url: str = "https://planetarycomputer.microsoft.com/api/sas/v1"
    lpdaac_stac_url: str = "https://data.lpdaac.earthdatacloud.nasa.gov/stac/LPCLOUD"

    # ``NoDecode`` stops pydantic-settings from JSON-decoding the raw env value
    # so the comma-separated form below reaches the validator untouched.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def raw_dir(self) -> Path:
        return self.storage_root / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.storage_root / "processed"

    @property
    def exports_dir(self) -> Path:
        return self.storage_root / "exports"

    @property
    def reports_dir(self) -> Path:
        return self.storage_root / "reports"

    @property
    def tmp_dir(self) -> Path:
        return self.storage_root / "tmp"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
