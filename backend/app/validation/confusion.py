"""Risk classification and confusion matrix (Signature-Challenge Property 3).

Flood/drought risk levels must come from *documented thresholds*, never magic
numbers, and the classifier must be scored against historical events with a
confusion matrix.  These functions are pure and deterministic:

* :func:`classify`          – apply a documented threshold to a value.
* :func:`confusion_matrix`  – TP/FP/FN/TN plus precision/recall/accuracy/F1.
* :func:`score_events`      – build the matrix from indicator + event records.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# documented comparison operators -> whether "above the reference" is the breach
_OPERATORS = {"gt", "gte", "lt", "lte", "between"}


def classify(value: float, threshold: Mapping[str, Any]) -> str:
    """Classify *value* against a documented *threshold* record.

    ``threshold`` must carry ``operator`` and ``value_low`` (and ``value_high``
    for ``between``).  Returns ``"flood"``, ``"drought"`` or ``"normal"``.
    The hazard direction is taken from ``threshold['direction']`` when present
    (defaults: ``gt``/``gte`` -> flood, ``lt``/``lte`` -> drought).
    """
    op = str(threshold["operator"]).lower()
    if op not in _OPERATORS:
        raise ValueError(f"unknown threshold operator: {op!r}")
    low = float(threshold["value_low"])
    high = float(threshold.get("value_high", low))
    direction = threshold.get("direction")
    if direction is None:
        direction = "flood" if op in ("gt", "gte") else "drought"
    breach = _is_breach(value, op, low, high)
    return direction if breach else "normal"


def _is_breach(value: float, op: str, low: float, high: float) -> bool:
    if op == "gt":
        return value > low
    if op == "gte":
        return value >= low
    if op == "lt":
        return value < low
    if op == "lte":
        return value <= low
    return value < low or value > high  # between: outside the band is a breach


def confusion_matrix(pairs: Sequence[tuple[bool, bool]]) -> dict[str, Any]:
    """Compute a confusion matrix from ``(predicted_positive, actual_positive)``."""
    tp = fp = fn = tn = 0
    for predicted, actual in pairs:
        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1
    total = tp + fp + fn + tn
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
        "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
        "accuracy": round((tp + tn) / total, 4) if total else None,
        "f1": _f1(tp, fp, fn),
    }


def _f1(tp: int, fp: int, fn: int) -> float | None:
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    if precision is None or recall is None or (precision + recall) == 0:
        return None
    return round(2 * precision * recall / (precision + recall), 4)


def score_events(
    indicators: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    threshold: Mapping[str, Any],
    *,
    positive_hazard: str = "flood",
) -> dict[str, Any]:
    """Score threshold-based predictions against historical *events*.

    ``indicators`` carry ``study_area``, ``date`` and ``value``; ``events``
    carry ``study_area``, ``date`` and ``outcome`` (the observed hazard or
    ``"none"``).  Rows are matched on (study_area, date).  The predicted class
    is ``classify(value, threshold)``; a prediction is "positive" when it
    equals *positive_hazard*.
    """
    index = {(i["study_area"], i["date"]): float(i["value"]) for i in indicators}
    pairs: list[tuple[bool, bool]] = []
    matched = 0
    for event in events:
        key = (event["study_area"], event["date"])
        if key not in index:
            continue
        matched += 1
        predicted = classify(index[key], threshold) == positive_hazard
        actual = str(event.get("outcome", "none")).lower() == positive_hazard
        pairs.append((predicted, actual))
    result = confusion_matrix(pairs)
    result["matched"] = matched
    result["positive_hazard"] = positive_hazard
    return result
