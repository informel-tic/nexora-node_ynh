"""Shared runtime context helpers for Nexora node agent."""

from __future__ import annotations

import os
from pathlib import Path

from .node_service import NodeService


def resolve_repo_root(current_file: str) -> Path:
    """Resolve the repository root from an adapter module path."""

    return Path(current_file).resolve().parents[2]


def build_service(current_file: str, state_path: str | None = None) -> NodeService:
    """Build a NodeService instance for the node agent."""

    repo_root = resolve_repo_root(current_file)
    return NodeService(repo_root, state_path or os.environ.get("NEXORA_STATE_PATH"))
