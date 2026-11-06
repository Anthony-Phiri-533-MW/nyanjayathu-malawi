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
    # Worker threads run handlers concurrently; each is lightweight (I/O bound).
    jobs_worker_count: int = 6
    jobs_max_attempts: int = 3

    # --- daily scheduler --------------------------------------------------
    # The scheduler thread enqueues one ``daily_pipeline`` job per UTC day.
    # It only touches data sources whose ``schedule_enabled`` flag is on, so
    # enabling the scheduler alone never triggers network traffic.
    scheduler_enabled: bool = True
    scheduler_hour_utc: int = Field(default=2, ge=0, le=23)
    scheduler_minute_utc: int = Field(default=0, ge=0, le=59)
    scheduler_tick_seconds: float = Field(default=60.0, gt=0)
    scheduler_lookback_days: int = Field(default=3, ge=1, le=60)

    # --- short-term forecasting ------------------------------------------
    forecast_enabled: bool = True
    # Comma-separated in the environment, e.g. FORECAST_INDICATOR_KEYS=water_extent,...
    forecast_indicator_keys: Annotated[list[str], NoDecode] = [
        "water_extent",
        "water_level_altimetry",
        "chlorophyll_a_proxy",
        "turbidity_proxy",
        "surface_water_temperature",
    ]
    forecast_horizon_days: int = Field(default=7, ge=1, le=60)
    forecast_min_points: int = Field(default=20, ge=8)
    forecast_n_folds: int = Field(default=3, ge=1, le=10)
    forecast_interval: float = Field(default=0.9, gt=0, lt=1)
    forecast_model_dir: Path = BASE_DIR.parent / "data" / "models"

    # --- HTTP / providers -------------------------------------------------
    http_timeout_seconds: float = 30.0
    chirps_base_url: str = "https://data.chc.ucsb.edu/products/CHIRPS-2.0"
    nasa_power_base_url: str = "https://power.larc.nasa.gov/api"
    planetary_computer_stac_url: str = "https://planetarycomputer.microsoft.com/api/stac/v1"
    planetary_computer_sas_url: str = "https://planetarycomputer.microsoft.com/api/sas/v1"
    lpdaac_stac_url: str = "https://data.lpdaac.earthdatacloud.nasa.gov/stac/LPCLOUD"

    # --- dashboard assistant (OpenAI-compatible chat completions API) -----
    # OpenRouter / Nemotron defaults.  Set AI_BASE_URL=https://openrouter.ai/api/v1
    # and AI_MODEL=nvidia/nemotron-nano-7b-v2 (or another Nemotron variant) plus
    # AI_API_KEY to enable the assistant on both admin and public dashboards.
    ai_base_url: str | None = "https://openrouter.ai/api/v1"
    ai_model: str | None = "nvidia/nemotron-nano-7b-v2"
    ai_api_key: str | None = None
    ai_timeout_seconds: float = Field(default=45.0, gt=0, le=120)

    # ``NoDecode`` stops pydantic-settings from JSON-decoding the raw env value
    # so the comma-separated form below reaches the validator untouched.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
    ]

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_url(cls, v: object) -> object:
        """Accept the connection strings managed platforms inject.

        Render, Railway and Heroku hand out ``postgres://`` or
        ``postgresql://`` URLs, while this project ships psycopg 3 (dialect
        ``postgresql+psycopg``).  Rewriting here means the same ``DATABASE_URL``
        variable works locally, in Docker Compose and on those platforms.
        """
        if not isinstance(v, str):
            return v
        if v.startswith("postgres://"):
            return "postgresql+psycopg://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            return "postgresql+psycopg://" + v[len("postgresql://") :]
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("forecast_indicator_keys", mode="before")
    @classmethod
    def _split_indicator_keys(cls, v: object) -> object:
        if isinstance(v, str):
            return [k.strip() for k in v.split(",") if k.strip()]
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
