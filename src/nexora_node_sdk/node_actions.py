"""Production-grade execution engine and backends for node-agent actions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .docker import docker_compose_up, write_compose_file
from .failover import apply_maintenance_mode, remove_maintenance_mode
from .governance import executive_report
from .operator_actions import AGENT_ACTION_CAPABILITIES, apply_branding
from .pra import build_restore_plan
from .privileged_actions import build_privileged_execution_plan
from .scoring import compute_pra_score
from .sync import detect_sync_conflicts

ActionHandler = Callable[[Any, dict[str, Any], bool], dict[str, Any]]
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ActionSpec:
    action: str
    handler: ActionHandler | None
    capacity_class: str
    requires_privileged_runtime: bool = False
    required_params: tuple[str, ...] = ()
    max_payload_bytes: int | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_trace_id(action: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{action.replace('/', '-')}-{stamp}"


_SENSITIVE_PARAM_TOKENS = ("secret", "token", "password", "key", "credential")
_OPAQUE_PARAM_TOKENS = ("content", "payload", "body", "data", "config", "manifest")
_MAX_AUDIT_STRING_LENGTH = 120
_MAX_AUDIT_COLLECTION_ITEMS = 20


def _audit_preview(value: Any) -> dict[str, Any]:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "redacted": True,
        "type": type(value).__name__,
        "size_bytes": len(serialized.encode("utf-8")),
    }


def _sanitize_param_value(value: Any, *, key_path: tuple[str, ...] = ()) -> Any:
    current_key = key_path[-1].lower() if key_path else ""
    if any(
        token in current_key for token in _SENSITIVE_PARAM_TOKENS + _OPAQUE_PARAM_TOKENS
    ):
        return _audit_preview(value)
    if isinstance(value, dict):
        return {
            key: _sanitize_param_value(nested, key_path=(*key_path, str(key)))
            for key, nested in value.items()
        }
    if isinstance(value, list):
        items = [
            _sanitize_param_value(item, key_path=(*key_path, f"[{index}]"))
            for index, item in enumerate(value[:_MAX_AUDIT_COLLECTION_ITEMS])
        ]
        if len(value) > _MAX_AUDIT_COLLECTION_ITEMS:
            items.append({"truncated": len(value) - _MAX_AUDIT_COLLECTION_ITEMS})
        return items
    if isinstance(value, tuple):
        return {
            "type": "tuple",
            "items": _sanitize_param_value(list(value), key_path=key_path),
        }
    if isinstance(value, str) and len(value) > _MAX_AUDIT_STRING_LENGTH:
        return {
            "type": "str",
            "length": len(value),
            "preview": value[:_MAX_AUDIT_STRING_LENGTH],
            "truncated": True,
        }
    return value


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _sanitize_param_value(value, key_path=(str(key),))
        for key, value in params.items()
    }


def _estimate_payload_size(params: dict[str, Any]) -> int:
    return len(str(params).encode("utf-8"))


def _extract_tenant_id(local_node: Any) -> str | None:
    """Extract tenant_id from a node summary-like object without assuming a strict type."""

    if isinstance(local_node, dict):
        tenant_id = local_node.get("tenant_id")
        return str(tenant_id) if tenant_id is not None else None
    if hasattr(local_node, "model_dump"):
        payload = local_node.model_dump()  # type: ignore[call-arg]
        if isinstance(payload, dict):
            tenant_id = payload.get("tenant_id")
            return str(tenant_id) if tenant_id is not None else None
    tenant_id = getattr(local_node, "tenant_id", None)
    return str(tenant_id) if tenant_id is not None else None


def _append_action_event(state: dict[str, Any], payload: dict[str, Any]) -> None:
    state.setdefault("node_action_events", []).append(payload)


def _base_result(
    spec: ActionSpec, *, dry_run: bool, changed: bool, trace_id: str
) -> dict[str, Any]:
    return {
        "success": True,
        "action": spec.action,
        "changed": changed,
        "dry_run": dry_run,
        "warnings": [],
        "errors": [],
        "rollback_hint": "rerun the inverse action or restore from state backup",
        "trace_id": trace_id,
        "observed_at": _utc_now(),
        "audit": {
            "category": "node-action",
            "capacity_class": spec.capacity_class,
            "roles": AGENT_ACTION_CAPABILITIES.get(spec.action, []),
        },
    }


def _error_result(
    spec: ActionSpec, *, dry_run: bool, trace_id: str, message: str
) -> dict[str, Any]:
    result = _base_result(spec, dry_run=dry_run, changed=False, trace_id=trace_id)
    result["success"] = False
    result["error"] = message
    result["errors"].append(message)
    result["warnings"].append(message)
    return result


def _blocked_result(
    spec: ActionSpec, *, dry_run: bool, trace_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    result = _error_result(
        spec,
        dry_run=dry_run,
        trace_id=trace_id,
        message=(
            f"{spec.action} is unavailable from the sandboxed node-agent service; "
            "run it from a privileged control-plane or operator context instead"
        ),
    )
    result["requires_privileged_runtime"] = True
    result["privileged_plan"] = build_privileged_execution_plan(spec.action, params)
    result["rollback_hint"] = result["privileged_plan"].get(
        "rollback_hint", result["rollback_hint"]
    )
    return result


def _validate_params(
    spec: ActionSpec, params: dict[str, Any], *, dry_run: bool, trace_id: str
) -> dict[str, Any] | None:
    missing = [name for name in spec.required_params if not params.get(name)]
    if missing:
        return _error_result(
            spec,
            dry_run=dry_run,
            trace_id=trace_id,
            message=f"Missing required parameter(s): {', '.join(missing)}",
        )
    if (
        spec.max_payload_bytes is not None
        and _estimate_payload_size(params) > spec.max_payload_bytes
    ):
        return _error_result(
            spec,
            dry_run=dry_run,
            trace_id=trace_id,
            message="Payload exceeds configured capacity limit",
        )
    return None


def _finalize_result(
    service: Any,
    spec: ActionSpec,
    result: dict[str, Any],
    *,
    trace_id: str,
    params: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    normalized = _base_result(spec, dry_run=dry_run, changed=False, trace_id=trace_id)
    normalized.update(result)
    normalized.setdefault("success", True)
    normalized.setdefault("changed", False)
    normalized.setdefault("warnings", [])
    normalized.setdefault("errors", [])
    normalized.setdefault(
        "rollback_hint", "rerun the inverse action or restore from state backup"
    )
    normalized.setdefault("trace_id", trace_id)
    normalized.setdefault("observed_at", _utc_now())
    audit = dict(normalized.get("audit", {}))
    audit.setdefault("category", "node-action")
    audit.setdefault("capacity_class", spec.capacity_class)
    audit.setdefault("roles", AGENT_ACTION_CAPABILITIES.get(spec.action, []))
    audit["params"] = _sanitize_params(params)
    normalized["audit"] = audit

    tenant_id = params.get("tenant_id")
    if tenant_id is None:
        try:
            tenant_id = _extract_tenant_id(service.local_node_summary())
        except Exception as exc:
            logger.warning("Unable to infer tenant_id from local node summary: %s", exc)
            tenant_id = None

    state = service.state.load()
    _append_action_event(
        state,
        {
            "timestamp": normalized["observed_at"],
            "action": spec.action,
            "trace_id": normalized["trace_id"],
            "success": normalized["success"],
            "changed": normalized["changed"],
            "dry_run": dry_run,
            "params": _sanitize_params(params),
            "rollback_hint": normalized.get("rollback_hint"),
            "tenant_id": tenant_id,
        },
    )
    service.state.save(state)
    return normalized


def run_inventory_refresh(
    service: Any, params: dict[str, Any], dry_run: bool
) -> dict[str, Any]:
    """Refresh inventory cache and persist a dated snapshot."""

    service.invalidate_cache()
    inventory = service.local_inventory()
    result = {
        "inventory_sections": sorted(inventory.keys()),
        "apps_count": len(inventory.get("apps", {}).get("apps", []))
        if isinstance(inventory.get("apps"), dict)
        else 0,
        "domains_count": len(inventory.get("domains", {}).get("domains", []))
        if isinstance(inventory.get("domains"), dict)
        else 0,
        "changed": not dry_run,
    }
    if dry_run:
        result["snapshot_preview"] = {"kind": "node-action-inventory-refresh"}
        return result

    state = service.state.load()
    local_node = service.local_node_summary()
    snapshot = {
        "timestamp": _utc_now(),
        "kind": "node-action-inventory-refresh",
        "inventory": inventory,
        "tenant_id": _extract_tenant_id(local_node),
    }
    state.setdefault("inventory_snapshots", []).append(snapshot)
    service.state.save(state)
    result["snapshot"] = {"kind": snapshot["kind"], "timestamp": snapshot["timestamp"]}
    return result


def run_permissions_sync(
    service: Any, params: dict[str, Any], dry_run: bool
) -> dict[str, Any]:
    """Sync local permissions into Nexora's managed desired-state snapshot."""

    current = service.inventory_slice("permissions")
    state = service.state.load()
    desired_state = state.setdefault("desired_state", {})
    existing = desired_state.get("permissions")
    conflicts = (
        detect_sync_conflicts(existing or {}, current)
        if isinstance(existing, dict)
        else []
    )
    will_change = existing != current
    result = {
        "changed": will_change and not dry_run,
        "conflict_count": len(conflicts),
        "conflicts": conflicts[:20],
    }
    if dry_run:
        result["planned_mode"] = (
            "create_baseline" if existing is None else "reconcile_from_local"
        )
        return result

    desired_state["permissions"] = current
    state["desired_state"] = desired_state
    state["last_permissions_sync"] = {
        "timestamp": _utc_now(),
        "mode": "create_baseline" if existing is None else "reconcile_from_local",
        "conflict_count": len(conflicts),
    }
    service.state.save(state)
    result["changed"] = will_change
    result["sync_mode"] = state["last_permissions_sync"]["mode"]
    return result


def run_healthcheck(
    service: Any, params: dict[str, Any], dry_run: bool
) -> dict[str, Any]:
    """Run a real healthcheck based on current service inventory and compatibility."""

    summary = service.local_node_summary().model_dump()
    compatibility = service.compatibility_report()["assessment"]
    alerts: list[str] = []
    checks = {
        "compatibility": compatibility.get("bootstrap_allowed", False),
        "backups_present": summary.get("backups_count", 0) > 0,
        "security_threshold": summary.get("security_score", 0) >= 50,
        "status_healthy": summary.get("status") == "healthy",
    }
    if not checks["compatibility"]:
        alerts.append("Compatibility policy blocks bootstrap or mutations")
    if not checks["backups_present"]:
        alerts.append("No backups detected")
    if not checks["status_healthy"]:
        alerts.append(f"Node status is {summary.get('status')}")
    return {
        "changed": False,
        "checks": checks,
        "alerts": alerts,
        "health_score": summary.get("health_score"),
        "security_score": summary.get("security_score"),
    }


def run_branding_apply(
    service: Any, params: dict[str, Any], dry_run: bool
) -> dict[str, Any]:
    """Apply the current branding state to the managed runtime state file."""

    state = service.state.load()
    branding = state.get("branding", {})
    result = {
        "changed": not dry_run,
        "branding": {
            "brand_name": branding.get("brand_name"),
            "accent": branding.get("accent"),
        },
    }
    if dry_run:
        return result
    applied = apply_branding(
        branding.get("brand_name", "Nexora"),
        branding.get("accent", "#5B6CFF"),
        state_path=str(service.state.path),
    )
    result["applied"] = applied
    result["success"] = bool(applied.get("success"))
    if not result["success"]:
        result["error"] = applied.get("error", "branding/apply failed")
        result.setdefault("errors", []).append(result["error"])
    return result


def run_pra_snapshot(
    service: Any, params: dict[str, Any], dry_run: bool
) -> dict[str, Any]:
    """Create a persistent PRA snapshot based on current inventory and governance data."""

    inventory = service.local_inventory()
    pra_score = compute_pra_score(inventory)
    node_id = service.identity().get("node_id", "local")
    tenant_id = params.get("tenant_id") or _extract_tenant_id(
        service.local_node_summary()
    )
    snapshot_id = (
        params.get("snapshot_id")
        or f"pra-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    )
    restore_plan = build_restore_plan(
        snapshot_id, target_node=node_id, offsite_source=params.get("offsite_source")
    )
    snapshot = {
        "snapshot_id": snapshot_id,
        "timestamp": _utc_now(),
        "kind": "node-action-pra-snapshot",
        "tenant_id": tenant_id,
        "inventory": inventory,
        "pra": pra_score,
        "executive_report": executive_report(inventory, node_id=node_id, has_pra=True),
        "restore_plan": restore_plan,
    }
    if dry_run:
        return {
            "changed": False,
            "snapshot_preview": {
                "snapshot_id": snapshot_id,
                "tenant_id": tenant_id,
                "restore_steps": restore_plan["steps"],
                "pra_score": pra_score["score"],
            },
        }

    state = service.state.load()
    state.setdefault("pra_snapshots", []).append(snapshot)
    service.state.save(state)
    return {
        "changed": True,
        "snapshot": {
            "snapshot_id": snapshot_id,
            "timestamp": snapshot["timestamp"],
            "tenant_id": tenant_id,
            "pra_score": pra_score["score"],
        },
        "restore_plan": restore_plan,
    }


def run_maintenance_enable(
    service: Any, params: dict[str, Any], dry_run: bool
) -> dict[str, Any]:
    """Enable maintenance mode for a domain using the failover helpers."""

    domain = str(params["domain"])
    message = str(params.get("message") or "Maintenance en cours")
    if dry_run:
        return {
            "changed": False,
            "planned_domain": domain,
            "planned_message": message,
            "maintenance_mode": "enable",
        }
    applied = apply_maintenance_mode(domain, message)
    return {
        "changed": bool(applied.get("success")),
        "maintenance_mode": "enable",
        "domain": domain,
        "result": applied,
        "success": bool(applied.get("success")),
        "error": applied.get("error"),
    }


def run_maintenance_disable(
    service: Any, params: dict[str, Any], dry_run: bool
) -> dict[str, Any]:
    """Disable maintenance mode for a domain using the failover helpers."""

    domain = str(params["domain"])
    if dry_run:
        return {
            "changed": False,
            "planned_domain": domain,
            "maintenance_mode": "disable",
        }
    removed = remove_maintenance_mode(domain)
    return {
        "changed": bool(removed.get("success")),
        "maintenance_mode": "disable",
        "domain": domain,
        "result": removed,
        "success": bool(removed.get("success")),
        "error": removed.get("error"),
    }


def run_docker_compose_apply(
    service: Any, params: dict[str, Any], dry_run: bool
) -> dict[str, Any]:
    """Write a compose file and optionally apply it through docker compose up."""

    compose_path = str(
        params.get("path")
        or (service.state.path.parent / "docker" / "docker-compose.yml")
    )
    content = params.get("content")
    detach = bool(params.get("detach", True))
    if not isinstance(content, str) or not content.strip():
        return {
            "success": False,
            "changed": False,
            "error": "docker/compose/apply requires a non-empty 'content' payload",
            "errors": ["docker/compose/apply requires a non-empty 'content' payload"],
        }
    if dry_run:
        return {
            "changed": False,
            "compose_path": compose_path,
            "planned_detach": detach,
            "line_count": len(content.splitlines()),
        }

    write_result = write_compose_file(content, compose_path)
    apply_result = docker_compose_up(compose_path, detach=detach)
    return {
        "changed": bool(write_result.get("written"))
        or bool(apply_result.get("success")),
        "compose_path": compose_path,
        "write_result": write_result,
        "apply_result": apply_result,
        "success": bool(apply_result.get("success")),
        "rollback_hint": f"run docker compose -f {compose_path} down to revert the deployment",
        "error": apply_result.get("error") if not apply_result.get("success") else None,
    }


ACTION_SPECS: dict[str, ActionSpec] = {
    "branding/apply": ActionSpec(
        "branding/apply", run_branding_apply, capacity_class="safe"
    ),
    "automation/install": ActionSpec(
        "automation/install",
        None,
        capacity_class="privileged",
        requires_privileged_runtime=True,
    ),
    "hooks/install": ActionSpec(
        "hooks/install",
        None,
        capacity_class="privileged",
        requires_privileged_runtime=True,
    ),
    "inventory/refresh": ActionSpec(
        "inventory/refresh", run_inventory_refresh, capacity_class="safe"
    ),
    "permissions/sync": ActionSpec(
        "permissions/sync", run_permissions_sync, capacity_class="safe"
    ),
    "pra/snapshot": ActionSpec("pra/snapshot", run_pra_snapshot, capacity_class="safe"),
    "maintenance/enable": ActionSpec(
        "maintenance/enable",
        run_maintenance_enable,
        capacity_class="safe",
        required_params=("domain",),
    ),
    "maintenance/disable": ActionSpec(
        "maintenance/disable",
        run_maintenance_disable,
        capacity_class="safe",
        required_params=("domain",),
    ),
    "docker/compose/apply": ActionSpec(
        "docker/compose/apply",
        run_docker_compose_apply,
        capacity_class="heavy",
        required_params=("content",),
        max_payload_bytes=131072,
    ),
    "healthcheck/run": ActionSpec(
        "healthcheck/run", run_healthcheck, capacity_class="safe"
    ),
}


class NodeActionEngine:
    """Canonical runtime for all node-agent actions."""

    def __init__(self, service: Any):
        self.service = service

    def describe(self, action: str) -> dict[str, Any]:
        spec = ACTION_SPECS[action]
        return {
            "action": action,
            "roles": AGENT_ACTION_CAPABILITIES.get(action, []),
            "capacity_class": spec.capacity_class,
            "requires_privileged_runtime": spec.requires_privileged_runtime,
            "required_params": list(spec.required_params),
            "max_payload_bytes": spec.max_payload_bytes,
        }

    def execute(
        self,
        action: str,
        *,
        dry_run: bool = False,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        spec = ACTION_SPECS.get(action)
        payload = dict(params or {})
        if spec is None:
            trace_id = _new_trace_id(action)
            unknown = _error_result(
                ActionSpec(action, None, capacity_class="unknown"),
                dry_run=dry_run,
                trace_id=trace_id,
                message="Unknown node action",
            )
            return _finalize_result(
                self.service,
                ActionSpec(action, None, capacity_class="unknown"),
                unknown,
                trace_id=trace_id,
                params=payload,
                dry_run=dry_run,
            )

        trace_id = _new_trace_id(action)
        validation_error = _validate_params(
            spec, payload, dry_run=dry_run, trace_id=trace_id
        )
        if validation_error is not None:
            return _finalize_result(
                self.service,
                spec,
                validation_error,
                trace_id=trace_id,
                params=payload,
                dry_run=dry_run,
            )

        if spec.requires_privileged_runtime:
            blocked = _blocked_result(
                spec, dry_run=dry_run, trace_id=trace_id, params=payload
            )
            return _finalize_result(
                self.service,
                spec,
                blocked,
                trace_id=trace_id,
                params=payload,
                dry_run=dry_run,
            )

        try:
            result = (
                spec.handler(self.service, payload, dry_run) if spec.handler else {}
            )
        except Exception as exc:  # pragma: no cover - defensive path
            result = _error_result(
                spec, dry_run=dry_run, trace_id=trace_id, message=str(exc)
            )
        return _finalize_result(
            self.service,
            spec,
            result,
            trace_id=trace_id,
            params=payload,
            dry_run=dry_run,
        )


def execute_node_action(
    service: Any,
    action: str,
    *,
    dry_run: bool = False,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a node action using the canonical local runtime engine."""

    return NodeActionEngine(service).execute(action, dry_run=dry_run, params=params)
