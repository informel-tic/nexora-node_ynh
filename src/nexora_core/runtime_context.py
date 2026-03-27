"""Shared runtime context helpers for Nexora platform adapters."""

from __future__ import annotations

import os
from pathlib import Path

from .orchestrator import NexoraService


def resolve_repo_root(current_file: str) -> Path:
    """Resolve the repository root from an adapter module path."""

    return Path(current_file).resolve().parents[2]


def build_service(current_file: str, state_path: str | None = None) -> NexoraService:
    """Build a Nexora service instance for API, agent, or MCP adapters."""

    repo_root = resolve_repo_root(current_file)
    return NexoraService(repo_root, state_path or os.environ.get("NEXORA_STATE_PATH"))
