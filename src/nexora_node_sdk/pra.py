"""PRA / backup / restore planning helpers for Nexora."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_backup_scope(
    scope: str, *, include_apps: list[str] | None = None
) -> dict[str, Any]:
    """Build a backup scope definition."""

    return {
        "scope": scope,
        "include_apps": include_apps or [],
        "generated_at": _utc_now_iso(),
    }


def build_restore_plan(
    snapshot_id: str, *, target_node: str, offsite_source: str | None = None
) -> dict[str, Any]:
    """Build a restore plan for a snapshot."""

    return {
        "snapshot_id": snapshot_id,
        "target_node": target_node,
        "offsite_source": offsite_source,
        "steps": [
            "validate_snapshot",
            "prepare_target",
            "restore_data",
            "verify_services",
        ],
        "generated_at": _utc_now_iso(),
    }
