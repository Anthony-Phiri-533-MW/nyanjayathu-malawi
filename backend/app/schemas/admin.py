"""Auth + Admin-module schemas."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.permissions import ALL_PERMISSION_KEYS, ROLE_ORDER


# --- auth -------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str
    permissions: list[str] = []


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    department: str | None = None
    is_active: bool
    roles: list[str] = []
    permissions: list[str] = []
    created_at: datetime
    updated_at: datetime | None = None
    last_login_at: datetime | None = None
    created_by_id: int | None = None

    @classmethod
    def from_user(cls, user) -> UserOut:
        roles = sorted({r.name for r in user.roles})
        from app.core.permissions import permissions_for_roles

        granted = permissions_for_roles(set(roles))
        # Super Administrators hold the wildcard "*"; expand it so the client
        # receives the concrete permission keys it gates the UI on.
        if "*" in granted:
            granted = set(ALL_PERMISSION_KEYS)

        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            department=user.department,
            is_active=user.is_active,
            roles=roles,
            permissions=sorted(p for p in granted if p in ALL_PERMISSION_KEYS),
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_login_at=user.last_login_at,
            created_by_id=user.created_by_id,
        )


class MeOut(UserOut):
    pass


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=72)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=20)
    new_password: str = Field(min_length=10, max_length=72)


# --- user management --------------------------------------------------------
class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=10, max_length=72)
    roles: list[str] = Field(default_factory=list)
    department: str | None = Field(default=None, max_length=200)
    is_active: bool = True

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, v: list[str]) -> list[str]:
        unknown = [r for r in v if r not in ROLE_ORDER]
        if unknown:
            raise ValueError(f"Unknown roles: {', '.join(unknown)}")
        if len(set(v)) != len(v):
            raise ValueError("Duplicate roles supplied")
        return v


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, min_length=10, max_length=72)
    is_active: bool | None = None
    roles: list[str] | None = None

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        unknown = [r for r in v if r not in ROLE_ORDER]
        if unknown:
            raise ValueError(f"Unknown roles: {', '.join(unknown)}")
        if len(set(v)) != len(v):
            raise ValueError("Duplicate roles supplied")
        return v

    @model_validator(mode="after")
    def _non_empty(self) -> UserUpdate:
        if not any([self.full_name, self.department, self.password, self.is_active is not None, self.roles]):
            raise ValueError("No fields to update")
        return self


class UserRolesUpdate(BaseModel):
    roles: list[str]

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, v: list[str]) -> list[str]:
        unknown = [r for r in v if r not in ROLE_ORDER]
        if unknown:
            raise ValueError(f"Unknown roles: {', '.join(unknown)}")
        if len(set(v)) != len(v):
            raise ValueError("Duplicate roles supplied")
        return v


class PasswordResetOut(BaseModel):
    """Returned once to the administrator so they can hand it to the user."""

    reset_token: str
    expires_at: datetime


# --- data sources -----------------------------------------------------------
class DataSourceCreate(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    provider_key: str = Field(min_length=2, max_length=60, pattern=r"^[a-z0-9_\-]+$")
    category: str
    dataset_name: str = ""
    dataset_identifier: str = ""
    description: str = ""
    is_enabled: bool = True
    coverage_geojson: dict | None = None
    temporal_start: date | None = None
    temporal_end: date | None = None
    variables: list[dict] | dict | None = None
    ingestion_config: dict | None = None
    auth_method: str = "none"
    credential_ref: str | None = Field(default=None, max_length=255)
    schedule_enabled: bool = False
    schedule_time_utc: str = Field(default="02:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    schedule_lookback_days: int = Field(default=3, ge=1, le=60)

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        from app.core.enums import DATA_SOURCE_CATEGORIES

        allowed = {c for c, _ in DATA_SOURCE_CATEGORIES}
        if v not in allowed:
            raise ValueError(f"category must be one of {sorted(allowed)}")
        return v

    @field_validator("auth_method")
    @classmethod
    def _auth(cls, v: str) -> str:
        from app.core.enums import AUTH_METHODS

        allowed = {a for a, _ in AUTH_METHODS}
        if v not in allowed:
            raise ValueError(f"auth_method must be one of {sorted(allowed)}")
        return v

    @field_validator("credential_ref")
    @classmethod
    def _ref(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not v.startswith(("env:", "file:", "secret:")):
            raise ValueError(
                "credential_ref must be a reference such as 'env:MY_TOKEN' - secret values are never stored"
            )
        # cheap guard against someone pasting an actual token/long secret
        if len(v) > 120 or " " in v:
            raise ValueError("credential_ref looks like a raw secret; use a reference name instead")
        return v

    @model_validator(mode="after")
    def _dates(self) -> DataSourceCreate:
        if self.temporal_start and self.temporal_end and self.temporal_start > self.temporal_end:
            raise ValueError("temporal_start must be before temporal_end")
        return self


class DataSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    dataset_name: str | None = None
    dataset_identifier: str | None = None
    description: str | None = None
    is_enabled: bool | None = None
    coverage_geojson: dict | None = None
    temporal_start: date | None = None
    temporal_end: date | None = None
    variables: list[dict] | dict | None = None
    ingestion_config: dict | None = None
    auth_method: str | None = None
    credential_ref: str | None = Field(default=None, max_length=255)
    schedule_enabled: bool | None = None
    schedule_time_utc: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    schedule_lookback_days: int | None = Field(default=None, ge=1, le=60)

    @field_validator("auth_method")
    @classmethod
    def _auth(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from app.core.enums import AUTH_METHODS

        allowed = {a for a, _ in AUTH_METHODS}
        if v not in allowed:
            raise ValueError(f"auth_method must be one of {sorted(allowed)}")
        return v

    @field_validator("credential_ref")
    @classmethod
    def _ref(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not v.startswith(("env:", "file:", "secret:")):
            raise ValueError("credential_ref must be a reference such as 'env:MY_TOKEN'")
        if len(v) > 120 or " " in v:
            raise ValueError("credential_ref looks like a raw secret; use a reference name instead")
        return v


class DataSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    provider_key: str
    category: str
    dataset_name: str
    dataset_identifier: str
    description: str
    is_enabled: bool
    coverage_geojson: dict | None = None
    temporal_start: date | None = None
    temporal_end: date | None = None
    variables: list | dict | None = None
    ingestion_config: dict | None = None
    auth_method: str
    credential_ref: str | None = None
    status: str
    last_test_at: datetime | None = None
    last_test_status: str | None = None
    last_test_message: str | None = None
    last_ingestion_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    error_status: str | None = None
    error_detail: str | None = None
    schedule_enabled: bool = False
    schedule_time_utc: str = "02:00"
    schedule_lookback_days: int = 3
    last_scheduled_at: datetime | None = None
    dataset_count: int = 0      # datasets actually retrieved through this source
    created_at: datetime
    updated_at: datetime | None = None


class ConnectionTestOut(BaseModel):
    source_id: int
    status: str            # verified | failed
    tested_at: datetime
    message: str
    latency_ms: int | None = None
    details: dict = {}


# --- thresholds -------------------------------------------------------------
class ThresholdCreate(BaseModel):
    indicator_key: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9_.\-]+$")
    indicator_name: str = Field(min_length=3, max_length=200)
    unit: str = Field(min_length=1, max_length=40)
    operator: str
    value_low: float | None = None
    value_high: float | None = None
    description: str = ""
    justification: str = ""
    reference: str = ""
    approval_status: str = "provisional"
    effective_from: date | None = None
    effective_to: date | None = None
    is_enabled: bool = True

    @field_validator("operator")
    @classmethod
    def _op(cls, v: str) -> str:
        if v not in ("gt", "gte", "lt", "lte", "between"):
            raise ValueError("operator must be one of gt|gte|lt|lte|between")
        return v

    @field_validator("approval_status")
    @classmethod
    def _appr(cls, v: str) -> str:
        if v not in ("provisional", "pending_review", "approved"):
            raise ValueError("approval_status must be provisional|pending_review|approved")
        return v

    @model_validator(mode="after")
    def _values(self) -> ThresholdCreate:
        if self.operator == "between":
            if self.value_low is None or self.value_high is None:
                raise ValueError("operator 'between' requires value_low and value_high")
            if self.value_low >= self.value_high:
                raise ValueError("value_low must be lower than value_high")
        elif self.value_low is None:
            raise ValueError(f"operator '{self.operator}' requires value_low")
        if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("effective_from must be before effective_to")
        return self


class ThresholdUpdate(BaseModel):
    indicator_name: str | None = Field(default=None, min_length=3, max_length=200)
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    operator: str | None = None
    value_low: float | None = None
    value_high: float | None = None
    description: str | None = None
    justification: str | None = None
    reference: str | None = None
    approval_status: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    is_enabled: bool | None = None
    change_note: str = ""

    @field_validator("operator")
    @classmethod
    def _op(cls, v: str | None) -> str | None:
        if v is not None and v not in ("gt", "gte", "lt", "lte", "between"):
            raise ValueError("operator must be one of gt|gte|lt|lte|between")
        return v

    @field_validator("approval_status")
    @classmethod
    def _appr(cls, v: str | None) -> str | None:
        if v is not None and v not in ("provisional", "pending_review", "approved"):
            raise ValueError("approval_status must be provisional|pending_review|approved")
        return v


class ThresholdVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    version: int
    change_note: str
    changed_by_email: str | None = None
    created_at: datetime
    snapshot: dict | None = None


class ThresholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    indicator_key: str
    indicator_name: str
    unit: str
    operator: str
    value_low: float | None = None
    value_high: float | None = None
    description: str
    justification: str
    reference: str
    approval_status: str
    effective_from: date | None = None
    effective_to: date | None = None
    is_enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime | None = None
    is_provisional: bool = False


# --- audit ------------------------------------------------------------------
class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    actor_id: int | None = None
    actor_email: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    outcome: str
    ip_address: str | None = None
    request_id: str | None = None
    message: str
    details: dict | None = None
