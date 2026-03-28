"""Synchronization logic: policies, permissions, branding, configs between nodes."""

from __future__ import annotations

import datetime
from typing import Any


def build_sync_plan(
    reference: dict[str, Any], targets: list[dict[str, Any]], sync_scope: str = "all"
) -> dict[str, Any]:
    """Build a synchronization plan from reference node to targets."""
    plan: list[dict[str, Any]] = []
    scopes = {"all", "governance", "inventory", "branding", "pra"}
    if sync_scope not in scopes:
        sync_scope = "all"

    ref_inv = reference.get("inventory", {})

    for target in targets:
        target_id = target.get("node_id", "unknown")
        tgt_inv = target.get("inventory", {})
        actions: list[dict[str, str]] = []

        if sync_scope in ("all", "governance"):
            ref_perms = (
                ref_inv.get("permissions", {}).get("permissions", {})
                if isinstance(ref_inv.get("permissions"), dict)
                else {}
            )
            tgt_perms = (
                tgt_inv.get("permissions", {}).get("permissions", {})
                if isinstance(tgt_inv.get("permissions"), dict)
                else {}
            )
            for perm, data in ref_perms.items():
                if perm not in tgt_perms:
                    actions.append(
                        {
                            "type": "add_permission",
                            "permission": perm,
                            "risk": "moderate",
                        }
                    )
                elif isinstance(data, dict) and isinstance(tgt_perms.get(perm), dict):
                    if sorted(data.get("allowed", [])) != sorted(
                        tgt_perms[perm].get("allowed", [])
                    ):
                        actions.append(
                            {
                                "type": "update_permission",
                                "permission": perm,
                                "risk": "moderate",
                            }
                        )

        if sync_scope in ("all", "inventory"):
            ref_apps = set()
            if isinstance(ref_inv.get("apps"), dict):
                for a in ref_inv["apps"].get("apps", []):
                    ref_apps.add(a.get("id", "") if isinstance(a, dict) else str(a))
            tgt_apps = set()
            if isinstance(tgt_inv.get("apps"), dict):
                for a in tgt_inv["apps"].get("apps", []):
                    tgt_apps.add(a.get("id", "") if isinstance(a, dict) else str(a))
            for app in ref_apps - tgt_apps:
                actions.append({"type": "install_app", "app": app, "risk": "high"})

        if sync_scope in ("all", "branding"):
            actions.append({"type": "sync_branding", "risk": "low"})

        if sync_scope in ("all", "pra"):
            actions.append({"type": "sync_pra_config", "risk": "low"})

        plan.append(
            {
                "target_node": target_id,
                "actions": actions,
                "action_count": len(actions),
            }
        )

    return {
        "scope": sync_scope,
        "reference_node": reference.get("node_id", "unknown"),
        "targets": plan,
        "total_actions": sum(p["action_count"] for p in plan),
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_sync_policy(settings: dict[str, Any]) -> dict[str, Any]:
    """Generate a default sync policy document."""
    return {
        "version": "1.0",
        "auto_sync": settings.get("auto_sync", False),
        "sync_interval_minutes": settings.get("sync_interval", 60),
        "sync_scopes": {
            "governance": {
                "enabled": True,
                "direction": "push",
                "risk_level": "moderate",
            },
            "branding": {"enabled": True, "direction": "push", "risk_level": "low"},
            "inventory": {"enabled": True, "direction": "pull", "risk_level": "low"},
            "apps": {"enabled": False, "direction": "push", "risk_level": "high"},
            "pra": {"enabled": True, "direction": "push", "risk_level": "low"},
        },
        "conflict_resolution": "reference_wins",
        "require_confirmation": True,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def detect_sync_conflicts(
    reference: dict[str, Any], target: dict[str, Any]
) -> list[dict[str, Any]]:
    """Detect simple sync conflicts between reference and target metadata."""

    conflicts = []
    for key in sorted(set(reference) & set(target)):
        if reference.get(key) != target.get(key):
            conflicts.append(
                {"key": key, "reference": reference.get(key), "target": target.get(key)}
            )
    return conflicts


def build_sync_job(plan: dict[str, Any], *, mode: str = "dry_run") -> dict[str, Any]:
    """Build a job wrapper around a sync plan."""

    return {
        "mode": mode,
        "plan": plan,
        "created_at": datetime.datetime.now().isoformat(),
        "status": "queued",
    }
