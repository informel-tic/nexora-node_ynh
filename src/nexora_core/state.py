"""JSON-backed state store and node lifecycle transition helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

NODE_STATUSES = [
    "discovered",
    "bootstrap_pending",
    "agent_installed",
    "attested",
    "registered",
    "healthy",
    "degraded",
    "draining",
    "revoked",
    "retired",
]

_ALLOWED_NODE_TRANSITIONS = {
    "discovered": {"bootstrap_pending", "revoked", "retired"},
    "bootstrap_pending": {"agent_installed", "revoked", "retired"},
    "agent_installed": {"attested", "degraded", "revoked", "retired"},
    "attested": {"registered", "degraded", "revoked", "retired"},
    "registered": {"healthy", "degraded", "draining", "revoked", "retired"},
    "healthy": {"degraded", "draining", "revoked", "retired"},
    "degraded": {"healthy", "draining", "revoked", "retired"},
    "draining": {"healthy", "revoked", "retired"},
    "revoked": {"retired", "bootstrap_pending"},
    "retired": set(),
}

DEFAULT_STATE = {
    "identity": {},
    "nodes": [],
    "branding": {},
    "fleet": {"mode": "single-node", "managed_nodes": [], "fleet_id": None},
    "blueprints": {},
    "imports": [],
    "inventory_snapshots": [],
    "enrollment_tokens": [],
    "enrollment_events": [],
    "lifecycle_events": [],
    "security_audit": [],
    "organizations": [],
    "tenants": [],
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def allowed_node_transitions(status: str) -> list[str]:
    return sorted(_ALLOWED_NODE_TRANSITIONS.get(status, set()))


def transition_node_status(node: dict[str, Any], target_status: str) -> dict[str, Any]:
    current_status = str(node.get("status") or "discovered")
    if target_status not in NODE_STATUSES:
        raise ValueError(f"Unsupported node status: {target_status}")
    if (
        current_status != target_status
        and target_status not in _ALLOWED_NODE_TRANSITIONS.get(current_status, set())
    ):
        raise ValueError(f"Transition not allowed: {current_status} -> {target_status}")

    updated = dict(node)
    updated["status"] = target_status
    updated["allowed_transitions"] = allowed_node_transitions(target_status)
    updated["status_updated_at"] = utc_now_iso()
    return updated


_NODE_DEFAULTS = {
    "status": "discovered",
    "enrollment_mode": None,
    "last_seen": None,
    "last_inventory_at": None,
    "enrolled_by": None,
    "token_id": None,
    "agent_version": None,
    "ynh_version": None,
    "debian_version": None,
    "credential_expires_at": None,
    "credential_revoked_at": None,
    "allowed_transitions": allowed_node_transitions("discovered"),
    "profile": None,
    "roles": [],
    "cordoned": False,
    "notes": [],
    "tenant_id": None,
    "organization_id": None,
}


def normalize_node_record(node: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(_NODE_DEFAULTS)
    normalized.update(node)
    status = str(normalized.get("status") or "discovered")
    if status not in NODE_STATUSES:
        status = "discovered"
    normalized["status"] = status
    normalized["allowed_transitions"] = allowed_node_transitions(status)
    return normalized


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> Dict[str, Any]:
        data = json.loads(json.dumps(DEFAULT_STATE))
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data.update(raw)
            except Exception as exc:
                logger.warning("StateStore failed to parse %s: %s", self.path, exc)
                data["_state_warning"] = {
                    "code": "state_parse_failed",
                    "path": str(self.path),
                    "message": str(exc),
                }
        data.setdefault("fleet", {}).setdefault("mode", "single-node")
        data["fleet"].setdefault("managed_nodes", [])
        data["fleet"].setdefault("fleet_id", None)
        data["nodes"] = [
            normalize_node_record(node)
            for node in data.get("nodes", [])
            if isinstance(node, dict)
        ]
        return data

    def save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(data)
        payload["nodes"] = [
            normalize_node_record(node)
            for node in payload.get("nodes", [])
            if isinstance(node, dict)
        ]
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
