"""Canonical Nexora capability catalog helpers."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CATALOG_PATH = Path(__file__).with_name("capabilities.yaml")


def load_capability_catalog(path: str | Path | None = None) -> dict[str, Any]:
    """Load the canonical capability catalog from YAML."""

    catalog_path = Path(path) if path else DEFAULT_CATALOG_PATH
    if not catalog_path.exists():
        return {"version": 1, "capabilities": []}
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {"version": 1, "capabilities": []}


def list_capabilities(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return the normalized list of capabilities."""

    catalog = load_capability_catalog(path)
    capabilities = catalog.get("capabilities", [])
    return capabilities if isinstance(capabilities, list) else []


def summarize_capabilities(path: str | Path | None = None) -> dict[str, Any]:
    """Summarize the canonical capability catalog."""

    capabilities = list_capabilities(path)
    by_domain = Counter()
    by_layer = Counter()
    by_status = Counter()
    for capability in capabilities:
        if not isinstance(capability, dict):
            continue
        by_domain[str(capability.get("domain", "unknown"))] += 1
        by_layer[str(capability.get("owner_layer", "unknown"))] += 1
        by_status[str(capability.get("status", "unknown"))] += 1
    return {
        "total": len(capabilities),
        "by_domain": dict(sorted(by_domain.items())),
        "by_layer": dict(sorted(by_layer.items())),
        "by_status": dict(sorted(by_status.items())),
    }


def capability_catalog_payload(path: str | Path | None = None) -> dict[str, Any]:
    """Return catalog + summary in a single API-friendly payload."""

    catalog = load_capability_catalog(path)
    return {
        "version": catalog.get("version", 1),
        "updated_at": catalog.get("updated_at"),
        "summary": summarize_capabilities(path),
        "capabilities": list_capabilities(path),
    }
