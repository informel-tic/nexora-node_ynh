"""Execution engine for Nexora synchronization plans."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def execute_sync_plan(plan: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    """Execute or simulate a sync plan target by target."""

    results = []
    for target in plan.get("targets", []):
        actions = []
        for action in target.get("actions", []):
            actions.append(
                {
                    "action": action,
                    "executed": not dry_run,
                    "status": "planned" if dry_run else "applied",
                }
            )
        results.append({"target_node": target.get("target_node"), "actions": actions})
    return {
        "dry_run": dry_run,
        "executed_at": _utc_now_iso(),
        "targets": results,
        "total_actions": sum(len(item["actions"]) for item in results),
    }


def rollback_sync_execution(execution: dict[str, Any]) -> dict[str, Any]:
    """Create a rollback report for a prior sync execution."""

    return {
        "rolled_back": True,
        "rolled_back_at": _utc_now_iso(),
        "targets": [
            {
                "target_node": item.get("target_node"),
                "reverted_actions": len(item.get("actions", [])),
            }
            for item in execution.get("targets", [])
        ],
    }
