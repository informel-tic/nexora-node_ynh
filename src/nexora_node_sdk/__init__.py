"""Public package exports for Nexora Node SDK (shared modules)."""

from __future__ import annotations

from .identity import NEXORA_IDENTITY

__all__ = ["NEXORA_IDENTITY", "NodeService"]


def __getattr__(name: str):
    """Lazy-load heavy exports to keep lightweight module imports testable."""

    if name == "NodeService":
        from .node_service import NodeService

        return NodeService
    raise AttributeError(name)
