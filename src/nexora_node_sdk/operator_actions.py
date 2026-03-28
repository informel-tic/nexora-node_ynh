"""Operator-level actions: safe, non-destructive operations that modify state.

These are the real execution backends for operator-mode tools.
All actions are audited and reversible where possible.
"""

from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path
from typing import Any

from .compatibility import assess_compatibility, load_compatibility_matrix
from .state import normalize_node_record, transition_node_status


AGENT_ACTION_CAPABILITIES = {
    "branding/apply": ["operator", "architect", "admin"],
    "permissions/sync": ["operator", "admin"],
    "inventory/refresh": ["observer", "operator", "admin"],
    "pra/snapshot": ["operator", "admin"],
    "maintenance/enable": ["operator", "admin"],
    "maintenance/disable": ["operator", "admin"],
    "docker/compose/apply": ["admin"],
    "healthcheck/run": ["observer", "operator", "admin"],
}


def list_supported_agent_actions() -> list[str]:
    """Return the sorted list of supported node-agent action endpoints."""

    return sorted(AGENT_ACTION_CAPABILITIES)


def summarize_agent_capabilities() -> dict[str, Any]:
    """Summarize roles and supported node-agent actions."""

    roles = sorted(
        {role for role_list in AGENT_ACTION_CAPABILITIES.values() for role in role_list}
    )
    return {"roles": roles, "actions": list_supported_agent_actions()}


def _ynh(cmd: list[str], timeout: int = 120) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["/usr/bin/yunohost"] + cmd + ["--output-as", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"PATH": "/usr/bin:/usr/sbin:/bin:/sbin", "HOME": "/root"},
        )
        result = (
            json.loads(proc.stdout)
            if proc.returncode == 0 and proc.stdout.strip()
            else {}
        )
        return {
            "success": proc.returncode == 0,
            "data": result,
            "error": proc.stderr.strip() if proc.returncode != 0 else "",
        }
    except Exception as e:
        return {"success": False, "data": {}, "error": str(e)}


def restart_service(service: str) -> dict[str, Any]:
    """Restart a YunoHost-managed service."""
    result = _ynh(["service", "restart", service])
    return {
        "action": "restart_service",
        "service": service,
        "success": result["success"],
        "error": result.get("error", ""),
        "timestamp": datetime.datetime.now().isoformat(),
    }


def create_backup(
    name: str = "", description: str = "", apps: str = ""
) -> dict[str, Any]:
    """Create a YunoHost backup."""
    cmd = ["backup", "create"]
    if name:
        cmd.extend(["--name", name])
    if description:
        cmd.extend(["--description", description])
    if apps:
        cmd.extend(["--apps"] + apps.split())
    result = _ynh(cmd, timeout=1800)
    return {
        "action": "create_backup",
        "name": name or "auto",
        "success": result["success"],
        "data": result.get("data", {}),
        "error": result.get("error", ""),
        "timestamp": datetime.datetime.now().isoformat(),
    }


def renew_certificate(domain: str) -> dict[str, Any]:
    """Renew Let's Encrypt certificate for a domain."""
    result = _ynh(["domain", "cert", "install", domain, "--no-checks"])
    return {
        "action": "renew_certificate",
        "domain": domain,
        "success": result["success"],
        "error": result.get("error", ""),
        "timestamp": datetime.datetime.now().isoformat(),
    }


def apply_branding(
    brand_name: str, accent: str, state_path: str = "/opt/nexora/var/state.json"
) -> dict[str, Any]:
    """Apply branding to Nexora state."""
    try:
        path = Path(state_path)
        data = json.loads(path.read_text()) if path.exists() else {}
        data["branding"] = {
            "brand_name": brand_name,
            "accent": accent,
            "portal_title": brand_name,
            "tagline": f"Portail {brand_name}",
            "sections": data.get("branding", {}).get(
                "sections", ["apps", "security", "monitoring", "pra", "fleet"]
            ),
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return {
            "action": "apply_branding",
            "success": True,
            "brand_name": brand_name,
            "accent": accent,
            "timestamp": datetime.datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "action": "apply_branding",
            "success": False,
            "error": str(e),
            "timestamp": datetime.datetime.now().isoformat(),
        }


def register_fleet_node(
    node_id: str,
    host: str,
    port: int = 38121,
    state_path: str = "/opt/nexora/var/state.json",
    *,
    enrollment_mode: str = "push",
    enrolled_by: str = "operator",
    token_id: str | None = None,
    agent_version: str | None = None,
    ynh_version: str | None = None,
    debian_version: str | None = None,
    target_status: str = "registered",
) -> dict[str, Any]:
    """Register a remote node in the fleet."""
    try:
        path = Path(state_path)
        data = json.loads(path.read_text()) if path.exists() else {}
        data.setdefault("fleet", {}).setdefault("managed_nodes", [])
        data.setdefault("nodes", [])
        if node_id not in data["fleet"]["managed_nodes"]:
            data["fleet"]["managed_nodes"].append(node_id)
        compatibility = assess_compatibility(
            "2.0.0", ynh_version, matrix=load_compatibility_matrix()
        )
        record = normalize_node_record(
            {
                "node_id": node_id,
                "hostname": host,
                "agent_port": port,
                "registered_at": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
                "last_seen": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "last_inventory_at": None,
                "enrollment_mode": enrollment_mode,
                "enrolled_by": enrolled_by,
                "token_id": token_id,
                "agent_version": agent_version or "2.0.0",
                "ynh_version": ynh_version,
                "yunohost_version": ynh_version,
                "debian_version": debian_version,
                "compatibility": compatibility,
            }
        )
        record = transition_node_status(record, target_status)
        data["nodes"] = [n for n in data["nodes"] if n.get("node_id") != node_id]
        data["nodes"].append(record)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        fleet_count = len(data["fleet"]["managed_nodes"])
        return {
            "action": "register_node",
            "success": True,
            "node_id": node_id,
            "fleet_size": fleet_count,
            "status": record["status"],
            "compatibility": compatibility,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
    except Exception as e:
        return {
            "action": "register_node",
            "success": False,
            "error": str(e),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }


def sync_branding_to_node(
    node_host: str, node_port: int, branding: dict, api_token: str
) -> dict[str, Any]:
    """Push branding to a remote node agent."""
    import httpx

    try:
        url = f"https://{node_host}:{node_port}/branding/apply"
        resp = httpx.post(
            url,
            json=branding,
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=30,
        )
        return {
            "action": "sync_branding",
            "success": resp.status_code == 200,
            "node": node_host,
            "status": resp.status_code,
            "timestamp": datetime.datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            "action": "sync_branding",
            "success": False,
            "node": node_host,
            "error": str(e),
            "timestamp": datetime.datetime.now().isoformat(),
        }


def execute_backup_rotation(
    keep_count: int = 7, state_path: str = "/opt/nexora/var/state.json"
) -> dict[str, Any]:
    """Rotate backups: keep the N most recent, delete older ones."""
    result = _ynh(["backup", "list"])
    if not result["success"]:
        return {
            "action": "backup_rotation",
            "success": False,
            "error": "Cannot list backups",
            "timestamp": datetime.datetime.now().isoformat(),
        }

    archives = result["data"].get("archives", [])
    if len(archives) <= keep_count:
        return {
            "action": "backup_rotation",
            "success": True,
            "kept": len(archives),
            "deleted": 0,
            "message": "Nothing to rotate",
            "timestamp": datetime.datetime.now().isoformat(),
        }

    to_delete = sorted(archives)[:-keep_count]
    deleted = []
    errors = []
    for name in to_delete:
        r = _ynh(["backup", "delete", name])
        if r["success"]:
            deleted.append(name)
        else:
            errors.append({"name": name, "error": r.get("error", "")})

    return {
        "action": "backup_rotation",
        "success": len(errors) == 0,
        "kept": keep_count,
        "deleted": len(deleted),
        "deleted_names": deleted,
        "errors": errors,
        "timestamp": datetime.datetime.now().isoformat(),
    }
