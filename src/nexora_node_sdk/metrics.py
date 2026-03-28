"""Persistent local metrics helpers for Nexora."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_metric(
    series: list[dict[str, Any]],
    name: str,
    value: float,
    *,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Append a metric sample to a local time series."""

    sample = {
        "name": name,
        "value": value,
        "labels": labels or {},
        "timestamp": _utc_now_iso(),
    }
    series.append(sample)
    return sample


def summarize_metric_series(series: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """Summarize a metric time series."""

    values = [float(sample["value"]) for sample in series if sample.get("name") == name]
    if not values:
        return {"name": name, "count": 0, "min": None, "max": None, "avg": None}
    return {
        "name": name,
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": round(sum(values) / len(values), 4),
    }
