"""Report Generation module schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REPORT_KINDS = ("periodic", "custom")
REPORT_PERIOD_TYPES = ("daily", "weekly", "monthly", "quarterly", "annual")
REPORT_FORMATS = ("pdf", "csv")
REPORT_SECTIONS = (
    "overview",      # scope: study areas, datasets, threshold counts in the period
    "indicators",    # per-indicator summary statistics computed from stored results
    "forecasts",     # recorded forecast values falling in the period
    "alerts",        # alerts first seen in the period + response status counts
)


class ReportCreate(BaseModel):
    """Request to build one report.

    ``kind="periodic"`` derives the period from ``period_type`` relative to
    today; ``kind="custom"`` requires an explicit ``period_start`` /
    ``period_end``.  ``include_sections`` selects which of the documented
    sections appear (default: all).  ``summary of statistics`` are computed
    from stored indicator results at build time - there is no separate
    statistics module.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=220)
    kind: Literal["periodic", "custom"] = "periodic"
    period_type: Literal["daily", "weekly", "monthly", "quarterly", "annual"] | None = None
    period_start: date | None = None
    period_end: date | None = None
    format: Literal["pdf", "csv"] = "pdf"
    study_area_id: int | None = None
    indicator_keys: list[str] | None = Field(default=None, max_length=20)
    include_sections: list[Literal["overview", "indicators", "forecasts", "alerts"]] = Field(
        default_factory=lambda: list(REPORT_SECTIONS)
    )
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _period_rules(self) -> ReportCreate:
        if self.kind == "periodic" and self.period_type is None:
            raise ValueError("periodic reports require period_type "
                             f"(one of {', '.join(REPORT_PERIOD_TYPES)})")
        if self.kind == "custom":
            if self.period_start is None or self.period_end is None:
                raise ValueError("custom reports require period_start and period_end")
            if self.period_end < self.period_start:
                raise ValueError("period_end must not be before period_start")
        return self


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    title: str
    kind: str
    period_type: str | None = None
    period_start: date
    period_end: date
    study_area_id: int | None = None
    study_area_name: str | None = None
    format: str
    status: str
    error: str | None = None
    file_name: str | None = None
    size_bytes: int | None = None
    download_url: str | None = None
    created_by_email: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    job_status: str | None = None


class ReportDetailOut(ReportOut):
    summary_json: dict | None = None
