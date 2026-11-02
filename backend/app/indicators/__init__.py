"""Indicator registry and orchestrator.

``compute_indicator`` resolves the requested definition, ensures declared
dependencies have usable results (computing them first when necessary), then
runs the matching computer and persists the rows.  Computers raise
``UnprocessableError`` when their inputs are absent; per-observation
incomputable cases instead return rows with ``value = NULL`` and a reason.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, UnprocessableError
from app.indicators import altimetry, climate, quality_proxies, water
from app.indicators.base import (
    IndicatorContext,
    Selection,
    persist,
)
from app.models import IndicatorDefinition, IndicatorResult, User

Computer = Callable[[IndicatorContext], list[IndicatorResult]]

COMPUTERS: dict[str, Computer] = {
    "water_extent": water.compute_water_extent,
    "water_extent_change": water.compute_water_extent_change,
    "water_level_altimetry": altimetry.compute_water_level_altimetry,
    "chlorophyll_a_proxy": quality_proxies.compute_chlorophyll_a_proxy,
    "turbidity_proxy": quality_proxies.compute_turbidity_proxy,
    "surface_water_temperature": quality_proxies.compute_surface_water_temperature,
    "rainfall_summary": climate.compute_rainfall_summary,
    "rainfall_anomaly": climate.compute_rainfall_anomaly,
    "temperature_summary": climate.compute_temperature_summary,
    "temperature_anomaly": climate.compute_temperature_anomaly,
}

# indicator -> indicator keys that must have results available first
DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "water_extent_change": ("water_extent",),
}


def indicator_keys() -> list[str]:
    return sorted(COMPUTERS)


def dependency_order() -> dict[str, tuple[str, ...]]:
    return dict(DEPENDENCIES)


def definition_for(db: Session, key: str) -> IndicatorDefinition:
    definition = db.execute(
        select(IndicatorDefinition).where(IndicatorDefinition.key == key)
    ).scalar_one_or_none()
    if definition is None:
        raise NotFoundError(f"Unknown indicator '{key}'", details={"supported": indicator_keys()})
    if not definition.is_enabled:
        raise UnprocessableError(f"Indicator '{key}' is disabled")
    return definition


def _has_results(db: Session, definition: IndicatorDefinition, selection: Selection) -> bool:
    stmt = select(IndicatorResult.id).where(
        IndicatorResult.indicator_key == definition.key,
        IndicatorResult.value.is_not(None),
    )
    if selection.study_area is not None:
        stmt = stmt.where(IndicatorResult.study_area_id == selection.study_area.id)
    if selection.datasets:
        stmt = stmt.where(
            IndicatorResult.dataset_id.in_([d.id for d in selection.datasets])
        )
    return db.execute(stmt.limit(1)).first() is not None


def compute_indicator(
    db: Session,
    *,
    key: str,
    selection: Selection,
    params: dict[str, Any] | None = None,
    actor: User | None = None,
    job_id: int | None = None,
    progress: Callable[[float, str], None] | None = None,
    _visited: set[str] | None = None,
) -> list[IndicatorResult]:
    """Compute one indicator, computing declared dependencies first if needed."""
    definition = definition_for(db, key)
    computer = COMPUTERS.get(key)
    if computer is None:
        raise UnprocessableError(
            f"No computation is implemented for indicator '{key}'",
            details={"supported": indicator_keys()},
        )

    report = progress or (lambda _f, _m="": None)
    visited = set(_visited or ())
    if key in visited:
        raise UnprocessableError(f"Circular indicator dependency involving '{key}'")
    visited.add(key)

    computed_dependencies: list[str] = []
    for dep_key in DEPENDENCIES.get(key, ()):
        dep_definition = definition_for(db, dep_key)
        if _has_results(db, dep_definition, selection):
            continue
        report(0.02, f"computing dependency {dep_key}")
        dep_results = compute_indicator(
            db,
            key=dep_key,
            selection=selection,
            params=params,
            actor=actor,
            job_id=job_id,
            progress=None,
            _visited=visited,
        )
        if not dep_results:
            raise UnprocessableError(
                f"Dependency '{dep_key}' produced no results for '{key}'"
            )
        computed_dependencies.append(dep_key)

    ctx = IndicatorContext(
        db=db,
        definition=definition,
        selection=selection,
        params=dict(params or {}),
        actor=actor,
        job_id=job_id,
        progress=report,
    )
    results = computer(ctx)
    if computed_dependencies:
        for row in results:
            provenance = dict(row.provenance_json or {})
            provenance["dependencies_computed"] = computed_dependencies
            row.provenance_json = provenance
    persist(db, results)
    return results
