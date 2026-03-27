"""Node lifecycle operations and safety rules.

This module implements TASK-3-1-4-1 and TASK-3-1-4-2 with a small set of
stateful lifecycle commands operating on Nexora's JSON state store.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .identity import generate_node_credentials
from .state import normalize_node_record, transition_node_status


_DESTRUCTIVE_ACTIONS = {"revoke", "retire", "delete"}


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as ISO8601."""

    return datetime.now(timezone.utc).isoformat()


# TASK-3-1-4-2: Operational safety rules.
def validate_lifecycle_action(
    node: dict[str, Any], action: str, *, confirmation: bool = False
) -> list[str]:
    """Validate lifecycle actions and return human-readable warnings."""

    warnings: list[str] = []
    roles = set(node.get("roles", []) or [])
    profile = str(node.get("profile") or "")
    status = str(node.get("status") or "discovered")

    if (
        action == "delete"
        and status in {"healthy", "degraded"}
        and (
            {"control-plane", "mail", "database"} & roles or "control-plane" in profile
        )
    ):
        raise ValueError(
            "Cannot delete a healthy critical node without prior retirement"
        )
    if action == "drain" and not confirmation and node.get("apps_count", 0) > 0:
        raise ValueError("Drain requires confirmation when workloads are present")
    if action in _DESTRUCTIVE_ACTIONS and not confirmation:
        warnings.append("Confirmation recommended for destructive lifecycle action")
    if (
        action == "re_enroll"
        and not node.get("credential_revoked_at")
        and status not in {"revoked", "retired"}
    ):
        warnings.append("Re-enrollment usually follows a revocation or retirement")
    return warnings


# TASK-3-1-4-1: Lifecycle commands.
def apply_lifecycle_action(
    state: dict[str, Any],
    *,
    node_id: str,
    action: str,
    operator: str,
    confirmation: bool = False,
    certs_dir: str | None = None,
) -> dict[str, Any]:
    """Apply a lifecycle action to a node record stored in the JSON state."""

    actions = {
        "drain",
        "cordon",
        "uncordon",
        "revoke",
        "retire",
        "rotate_credentials",
        "re_enroll",
        "delete",
    }
    if action not in actions:
        raise ValueError(f"Unsupported lifecycle action: {action}")

    nodes = state.setdefault("nodes", [])
    index = next(
        (i for i, item in enumerate(nodes) if item.get("node_id") == node_id), None
    )
    if index is None:
        raise ValueError(f"Unknown node: {node_id}")

    node = normalize_node_record(nodes[index])
    warnings = validate_lifecycle_action(node, action, confirmation=confirmation)
    rollback_hint = "re-run registration or restore node state from JSON backup"

    if action == "drain":
        node = transition_node_status(node, "draining")
        node.setdefault("notes", []).append("TASK-3-1-4-1: node drained")
    elif action == "cordon":
        node["cordoned"] = True
        node["cordoned_at"] = _utc_now_iso()
    elif action == "uncordon":
        node["cordoned"] = False
        node["uncordoned_at"] = _utc_now_iso()
    elif action == "revoke":
        node = transition_node_status(node, "revoked")
        node["credential_revoked_at"] = _utc_now_iso()
    elif action == "retire":
        if node.get("status") != "revoked":
            node = transition_node_status(node, "revoked")
        node = transition_node_status(node, "retired")
        node["retired_at"] = _utc_now_iso()
    elif action == "rotate_credentials":
        if not certs_dir:
            raise ValueError("certs_dir is required to rotate credentials")
        fleet_id = str(state.get("fleet", {}).get("fleet_id") or "fleet-local")
        creds = generate_node_credentials(node_id, fleet_id, certs_dir)
        node["token_id"] = creds["token_id"]
        node["credential_expires_at"] = creds["expires_at"]
        node["credential_revoked_at"] = None
        node["cert_path"] = creds["cert_path"]
        node["key_path"] = creds["key_path"]
        rollback_hint = (
            "revoke rotated credentials and re-issue prior certificate bundle"
        )
    elif action == "re_enroll":
        node["status"] = "bootstrap_pending"
        node["allowed_transitions"] = ["agent_installed", "retired", "revoked"]
        node["reenroll_requested_at"] = _utc_now_iso()
    elif action == "delete":
        nodes.pop(index)
        state.setdefault("fleet", {}).setdefault("managed_nodes", [])
        state["fleet"]["managed_nodes"] = [
            managed for managed in state["fleet"]["managed_nodes"] if managed != node_id
        ]
        state.setdefault("lifecycle_events", []).append(
            {
                "timestamp": _utc_now_iso(),
                "node_id": node_id,
                "tenant_id": node.get("tenant_id"),
                "action": action,
                "operator": operator,
                "warnings": warnings,
            }
        )
        return {
            "node_id": node_id,
            "action": action,
            "changed": True,
            "warnings": warnings,
            "rollback_hint": "restore node record from state snapshot if deletion was accidental",
        }

    node["last_operator"] = operator
    node["last_action"] = action
    nodes[index] = normalize_node_record(node)
    state.setdefault("lifecycle_events", []).append(
        {
            "timestamp": _utc_now_iso(),
            "node_id": node_id,
            "tenant_id": node.get("tenant_id"),
            "action": action,
            "operator": operator,
            "warnings": warnings,
        }
    )
    return {
        "node_id": node_id,
        "action": action,
        "changed": True,
        "warnings": warnings,
        "rollback_hint": rollback_hint,
        "node": nodes[index],
    }
