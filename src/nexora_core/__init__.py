"""Public package exports for Nexora Core."""

from __future__ import annotations

from .identity import NEXORA_IDENTITY

__all__ = ["NEXORA_IDENTITY", "NexoraService"]


def __getattr__(name: str):
    """Lazy-load heavy exports to keep lightweight module imports testable."""

    if name == "NexoraService":
        from .orchestrator import NexoraService

        return NexoraService
    raise AttributeError(name)
