"""Heartbeat and inventory snapshot helpers for Nexora fleets."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_heartbeat(
    node_id: str, *, status: str, roles: list[str], inventory_version: str = "1.0"
) -> dict[str, Any]:
    """Create a versioned heartbeat payload for a node."""

    return {
        "node_id": node_id,
        "status": status,
        "roles": roles,
        "inventory_version": inventory_version,
        "sent_at": _utc_now_iso(),
    }


def record_heartbeat(
    state: dict[str, Any], heartbeat: dict[str, Any]
) -> dict[str, Any]:
    """Store a heartbeat in the JSON state cache."""

    state.setdefault("heartbeats", []).append(heartbeat)
    state.setdefault("inventory_snapshots", []).append(
        {
            "timestamp": heartbeat["sent_at"],
            "kind": "heartbeat",
            "node_id": heartbeat["node_id"],
            "inventory_version": heartbeat["inventory_version"],
            "tenant_id": heartbeat.get("tenant_id"),
        }
    )
    return heartbeat


def summarize_heartbeat_state(heartbeats: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize heartbeat freshness and node count."""

    latest = {entry["node_id"]: entry for entry in heartbeats if entry.get("node_id")}
    return {
        "total_nodes": len(latest),
        "latest_by_node": latest,
        "last_seen_at": max(
            (entry["sent_at"] for entry in latest.values()), default=None
        ),
    }
