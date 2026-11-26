"""Pipeline pattern: a chain of processing steps for ingest → indicator → alert.

Each ``PipelineStep`` is a callable that receives a context dictionary and
returns a (possibly mutated) copy.  The ``Pipeline`` class holds an ordered
list of steps and executes them sequentially.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


StepFn = Callable[["PipelineContext"], "PipelineContext"]


@dataclass
class PipelineContext:
    """Mutable context passed between pipeline steps.

    Attributes
    ----------
    raw_data : bytes | None
        Downloaded sensor bundle.
    windowed_data : bytes | None
        Data clipped to study‑area bbox.
    calibrated : dict | None
        Calibration parameters (scale, offset, units).
    indicator_result : dict | None
        Result of a spectral‑index strategy (value, unit, quality_flag, …).
    quality_flag : str | None
        Final quality flag after evaluation.
    alert : dict | None
        Generated disaster alert (or ``None`` if no alert).
    error : str | None
        Human‑readable error message if a step fails.
    """
    raw_data: Optional[bytes] = None
    windowed_data: Optional[bytes] = None
    calibrated: Optional[Dict[str, Any]] = None
    indicator_result: Optional[Dict[str, Any]] = None
    quality_flag: Optional[str] = None
    alert: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PipelineStep:
    """A single stage in the processing pipeline."""

    def __init__(self, name: str, fn: StepFn) -> None:
        self.name = name
        self.fn = fn

    def run(self, ctx: PipelineContext) -> PipelineContext:
        """Execute the step, catching any exception and storing it in ``ctx.error``."""
        try:
            return self.fn(ctx)
        except Exception as exc:  # noqa: BLE001
            ctx.error = f"[{self.name}] {exc}"
            return ctx


class Pipeline:
    """Ordered sequence of ``PipelineStep`` instances."""

    def __init__(self, steps: Optional[List[PipelineStep]] = None) -> None:
        self.steps: List[PipelineStep] = steps if steps is not None else []

    def add(self, step: PipelineStep) -> None:
        self.steps.append(step)

    def run(self, initial_ctx: PipelineContext = PipelineContext()) -> PipelineContext:
        ctx = initial_ctx
        for step in self.steps:
            ctx = step.run(ctx)
            # Early‑exit if a fatal error occurred and the pipeline is not
            # designed to continue.
            if ctx.error and "fatal" in ctx.error.lower():
                break
        return ctx