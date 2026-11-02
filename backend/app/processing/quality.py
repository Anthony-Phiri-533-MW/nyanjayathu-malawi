"""Missing-data assessment and quality-flag rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Rule version bumps whenever flag logic changes (recorded on assessments).
QUALITY_RULE_VERSION = "1.0.0"

# Rule thresholds (documented defaults; all reported in the assessment row)
COVERAGE_INSUFFICIENT = 0.50     # < 50% valid pixels inside the footprint
COVERAGE_LOW = 0.80              # < 80% valid pixels -> LOW_QUALITY
CLOUD_HEAVY = 0.50               # > 50% cloud within the footprint
CLOUD_MODERATE = 0.10            # > 10% cloud within the footprint -> LOW_QUALITY
MISSING_ALL = 0.001              # essentially no valid pixels

# severity order used to pick the primary flag (first match wins)
_FLAG_PRIORITY = (
    "MISSING_DATA",
    "PROCESSING_FAILED",
    "INSUFFICIENT_COVERAGE",
    "CLOUD_CONTAMINATED",
    "LOW_QUALITY",
    "UNVALIDATED",
    "VALID",
)


@dataclass
class MissingDataStats:
    total_pixels: int
    valid_pixels: int
    missing_pixels: int
    valid_fraction: float
    missing_fraction: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_pixels": self.total_pixels,
            "valid_pixels": self.valid_pixels,
            "missing_pixels": self.missing_pixels,
            "valid_fraction": round(self.valid_fraction, 6),
            "missing_fraction": round(self.missing_fraction, 6),
        }


def assess_missing(valid_mask: np.ndarray, footprint: np.ndarray | None = None) -> MissingDataStats:
    mask = np.asarray(valid_mask, dtype=bool)
    if footprint is not None:
        mask = mask & np.asarray(footprint, dtype=bool)
        total = int(np.asarray(footprint, dtype=bool).sum())
        valid = int(mask.sum())
    else:
        total = int(mask.size)
        valid = int(mask.sum())
    missing = max(0, total - valid)
    return MissingDataStats(
        total_pixels=total,
        valid_pixels=valid,
        missing_pixels=missing,
        valid_fraction=(valid / total) if total else 0.0,
        missing_fraction=(missing / total) if total else 1.0,
    )


@dataclass
class QualityDecision:
    flag: str                      # primary flag
    reason: str
    all_flags: list[str]
    reasons: list[dict[str, str]]  # [{flag, reason}, ...]
    details: dict[str, Any] = field(default_factory=dict)


def evaluate_quality(
    *,
    coverage_fraction: float | None = None,
    cloud_fraction: float | None = None,
    missing: MissingDataStats | None = None,
    unvalidated: bool = False,
    processing_failed: bool = False,
    extra_flags: list[tuple[str, str]] | None = None,
) -> QualityDecision:
    """Explicit, testable flag rules.

    ``coverage_fraction`` = usable pixels / footprint pixels.
    ``cloud_fraction``    = cloud-affected pixels / footprint pixels.
    """
    reasons: dict[str, str] = {}
    cov = coverage_fraction
    cld = cloud_fraction

    if processing_failed:
        reasons["PROCESSING_FAILED"] = "the processing run failed before a result was produced"

    if missing is not None and (missing.total_pixels == 0 or missing.valid_fraction <= MISSING_ALL):
        reasons["MISSING_DATA"] = (
            f"no usable pixels ({missing.valid_pixels}/{missing.total_pixels} valid)"
        )

    if cov is not None:
        if cov < COVERAGE_INSUFFICIENT:
            reasons["INSUFFICIENT_COVERAGE"] = (
                f"valid coverage {cov:.0%} is below the {COVERAGE_INSUFFICIENT:.0%} minimum"
            )
        elif cov < COVERAGE_LOW:
            reasons["LOW_QUALITY"] = f"valid coverage {cov:.0%} is below the {COVERAGE_LOW:.0%} target"

    if cld is not None:
        if cld > CLOUD_HEAVY:
            reasons["CLOUD_CONTAMINATED"] = f"cloud affects {cld:.0%} of the footprint (> {CLOUD_HEAVY:.0%})"
        elif cld > CLOUD_MODERATE:
            reasons.setdefault("LOW_QUALITY", f"cloud affects {cld:.0%} of the footprint (> {CLOUD_MODERATE:.0%})")

    if unvalidated:
        reasons["UNVALIDATED"] = (
            "estimate/proxy output that has not been validated against in-situ reference measurements"
        )

    for flag, reason in extra_flags or []:
        reasons.setdefault(flag, reason)

    if not reasons:
        reasons["VALID"] = (
            f"coverage {cov:.0%}" + (f", cloud {cld:.0%}" if cld is not None else "") + "; all quality rules passed"
            if cov is not None
            else "all quality rules passed"
        )

    # primary flag = highest severity present; VALID only if it's the only one
    if list(reasons.keys()) == ["VALID"]:
        primary = "VALID"
    else:
        primary = next((f for f in _FLAG_PRIORITY if f in reasons and f != "VALID"), "LOW_QUALITY")
        reasons.pop("VALID", None)

    decision_reasons = [{"flag": f, "reason": reasons[f]} for f in _FLAG_PRIORITY if f in reasons]
    return QualityDecision(
        flag=primary,
        reason=decision_reasons[0]["reason"] if decision_reasons else "",
        all_flags=[r["flag"] for r in decision_reasons],
        reasons=decision_reasons,
        details={
            "coverage_fraction": cov,
            "cloud_fraction": cld,
            "missing": missing.as_dict() if missing else None,
            "rule_version": QUALITY_RULE_VERSION,
        },
    )
