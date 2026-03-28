"""Surface registry for Nexora capability-to-interface mapping."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nexora_node_sdk.capabilities import list_capabilities, load_capability_catalog

DEFAULT_CATALOG_PATH = Path(__file__).with_name("capabilities.yaml")

SURFACES = ("rest", "mcp", "console")


class SurfaceRegistry:
    """Loads the canonical capability catalog and provides surface queries."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else DEFAULT_CATALOG_PATH
        self._catalog = load_capability_catalog(self._path)
        self._capabilities = list_capabilities(self._path)
        self._by_id: dict[str, dict[str, Any]] = {
            cap["id"]: cap
            for cap in self._capabilities
            if isinstance(cap, dict) and "id" in cap
        }

    # ── Core accessors ───────────────────────────────────────────────────

    def get_capability(self, cap_id: str) -> dict[str, Any] | None:
        """Return the full capability definition by id, or None."""
        return self._by_id.get(cap_id)

    def list_all(self) -> list[dict[str, Any]]:
        """Return all capabilities."""
        return list(self._capabilities)

    def list_by_surface(self, surface: str) -> list[dict[str, Any]]:
        """Return all capabilities that expose at least one entry on *surface*."""
        results: list[dict[str, Any]] = []
        for cap in self._capabilities:
            if not isinstance(cap, dict):
                continue
            surfaces = cap.get("surfaces", {})
            entries = surfaces.get(surface, [])
            if isinstance(entries, list) and len(entries) > 0:
                results.append(cap)
        return results

    def list_by_domain(self, domain: str) -> list[dict[str, Any]]:
        """Return all capabilities belonging to a given domain."""
        return [
            cap
            for cap in self._capabilities
            if isinstance(cap, dict) and cap.get("domain") == domain
        ]

    # ── Parity analysis ──────────────────────────────────────────────────

    def parity_report(self) -> dict[str, Any]:
        """Analyze which capabilities lack which surfaces.

        Returns a dict with:
        - full_parity: list of cap ids covered by all 3 surfaces
        - gaps: list of {id, missing: [surface names]}
        - surface_counts: {rest: N, mcp: N, console: N}
        """
        full_parity: list[str] = []
        gaps: list[dict[str, Any]] = []
        surface_counts: dict[str, int] = {s: 0 for s in SURFACES}

        for cap in self._capabilities:
            if not isinstance(cap, dict):
                continue
            cap_id = cap.get("id", "unknown")
            surfaces = cap.get("surfaces", {})
            missing: list[str] = []
            for s in SURFACES:
                entries = surfaces.get(s, [])
                has_entries = isinstance(entries, list) and len(entries) > 0
                if has_entries:
                    surface_counts[s] += 1
                else:
                    missing.append(s)
            if not missing:
                full_parity.append(cap_id)
            else:
                gaps.append({"id": cap_id, "missing": missing})

        return {
            "total_capabilities": len(self._capabilities),
            "full_parity": full_parity,
            "full_parity_count": len(full_parity),
            "gaps": gaps,
            "gaps_count": len(gaps),
            "surface_counts": surface_counts,
        }

    def coverage_score(self) -> float:
        """Percentage of capabilities covered by all 3 core surfaces (rest, mcp, console).

        Returns a float between 0.0 and 100.0.
        """
        total = len(self._capabilities)
        if total == 0:
            return 0.0
        report = self.parity_report()
        return round(report["full_parity_count"] / total * 100, 1)

    # ── Serialization ────────────────────────────────────────────────────

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON-friendly summary of the registry state."""
        report = self.parity_report()
        return {
            "version": self._catalog.get("version", 1),
            "updated_at": self._catalog.get("updated_at"),
            "total_capabilities": report["total_capabilities"],
            "coverage_score": self.coverage_score(),
            "surface_counts": report["surface_counts"],
            "full_parity": report["full_parity"],
            "gaps": report["gaps"],
        }
