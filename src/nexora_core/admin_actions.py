"""Admin-level actions: destructive operations with full audit trail.

Every admin action is logged, requires confirmation in API mode,
and produces a rollback hint.
"""

from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path
from typing import Any

try:
    from .blueprints import resolve_blueprint_plan
except ImportError:  # pragma: no cover - absent in nexora-node_ynh split
    resolve_blueprint_plan = None  # type: ignore[assignment]
from .domain_models import Blueprint
from .preflight import build_install_preflight, build_upgrade_preflight


def _ynh(cmd: list[str], timeout: int = 300) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["/usr/bin/yunohost"] + cmd + ["--output-as", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"PATH": "/usr/bin:/usr/sbin:/bin:/sbin", "HOME": "/root"},
        )
        data = {}
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                data = {"raw": proc.stdout.strip()}
        return {
            "success": proc.returncode == 0,
            "data": data,
            "error": proc.stderr.strip() if proc.returncode != 0 else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "data": {}, "error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"success": False, "data": {}, "error": str(e)}


def _audit_log(action: str, details: dict[str, Any]):
    """Log admin action to audit file."""
    try:
        log_path = Path("/var/log/yunohost-mcp-server/admin-actions.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "action": action,
            **details,
        }
        with log_path.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(
            f"[nexora.admin_actions] audit log fallback: unable to write admin audit event: {exc}"
        )


def install_app(
    app_id: str, domain: str, path: str = "/", label: str = "", args: str = ""
) -> dict[str, Any]:
    """Install a YunoHost application."""
    preflight = build_install_preflight(app_id, domain, path, args)
    if not preflight.get("allowed"):
        error = "; ".join(
            preflight.get("blocking_issues", [])
            or [preflight.get("status", "preflight_failed")]
        )
        _audit_log(
            "install_app_rejected",
            {
                "app": app_id,
                "domain": domain,
                "path": path,
                "success": False,
                "error": error,
            },
        )
        return {
            "action": "install_app",
            "app": app_id,
            "domain": preflight.get("domain", domain),
            "path": preflight.get("path", path),
            "success": False,
            "data": {},
            "error": error,
            "warnings": preflight.get("warnings", []),
            "profile": preflight.get("profile")
            or {"app_id": app_id, "automation": "manual_review_required"},
            "preflight": preflight,
            "rollback": None,
            "timestamp": datetime.datetime.now().isoformat(),
        }

    request = (
        preflight.get("normalized_request", {})
        if isinstance(preflight.get("normalized_request"), dict)
        else {}
    )
    install_args = f"domain={preflight['domain']}&path={preflight['path']}"
    if request.get("args_string"):
        install_args += f"&{request['args_string']}"
    cmd = ["app", "install", app_id, "--args", install_args]
    if label:
        cmd.extend(["--label", label])
    result = _ynh(cmd, timeout=600)
    _audit_log(
        "install_app",
        {
            "app": app_id,
            "domain": preflight["domain"],
            "path": preflight["path"],
            "success": result["success"],
        },
    )
    return {
        "action": "install_app",
        "app": app_id,
        "domain": preflight["domain"],
        "path": preflight["path"],
        "success": result["success"],
        "data": result.get("data", {}),
        "error": result.get("error", ""),
        "warnings": preflight.get("warnings", []),
        "profile": preflight.get("profile"),
        "preflight": preflight,
        "rollback": f"yunohost app remove {app_id}" if result["success"] else None,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def remove_app(app_id: str) -> dict[str, Any]:
    """Remove a YunoHost application."""
    # Get app info before removal for rollback
    info = _ynh(["app", "info", app_id])
    result = _ynh(["app", "remove", app_id])
    _audit_log("remove_app", {"app": app_id, "success": result["success"]})
    return {
        "action": "remove_app",
        "app": app_id,
        "success": result["success"],
        "error": result.get("error", ""),
        "rollback": "Restore from backup" if result["success"] else None,
        "pre_removal_info": info.get("data", {}) if info["success"] else {},
        "timestamp": datetime.datetime.now().isoformat(),
    }


def upgrade_app(app_id: str = "") -> dict[str, Any]:
    """Upgrade one or all YunoHost applications."""
    preflight = build_upgrade_preflight(app_id)
    if not preflight.get("allowed"):
        error = "; ".join(
            preflight.get("blocking_issues", [])
            or [preflight.get("status", "preflight_failed")]
        )
        _audit_log(
            "upgrade_app_rejected",
            {"app": app_id or "all", "success": False, "error": error},
        )
        return {
            "action": "upgrade_app",
            "app": app_id or "all",
            "success": False,
            "data": {},
            "error": error,
            "warnings": preflight.get("warnings", []),
            "preflight": preflight,
            "rollback": None,
            "timestamp": datetime.datetime.now().isoformat(),
        }

    cmd = ["app", "upgrade"]
    if app_id:
        cmd.append(app_id)
    result = _ynh(cmd, timeout=900)
    _audit_log("upgrade_app", {"app": app_id or "all", "success": result["success"]})
    return {
        "action": "upgrade_app",
        "app": app_id or "all",
        "success": result["success"],
        "data": result.get("data", {}),
        "error": result.get("error", ""),
        "warnings": preflight.get("warnings", []),
        "preflight": preflight,
        "rollback": "Restore from pre-upgrade backup",
        "timestamp": datetime.datetime.now().isoformat(),
    }


def restore_backup(name: str, apps: str = "", system: str = "") -> dict[str, Any]:
    """Restore a YunoHost backup."""
    cmd = ["backup", "restore", name]
    if apps:
        cmd.extend(["--apps"] + apps.split())
    if system:
        cmd.extend(["--system"] + system.split())
    result = _ynh(cmd, timeout=3600)
    _audit_log("restore_backup", {"name": name, "success": result["success"]})
    return {
        "action": "restore_backup",
        "name": name,
        "success": result["success"],
        "error": result.get("error", ""),
        "timestamp": datetime.datetime.now().isoformat(),
    }


def create_user(
    username: str, fullname: str, domain: str, password: str
) -> dict[str, Any]:
    """Create a YunoHost user."""
    result = _ynh(
        [
            "user",
            "create",
            username,
            "--fullname",
            fullname,
            "--domain",
            domain,
            "--password",
            password,
        ]
    )
    _audit_log(
        "create_user",
        {"username": username, "domain": domain, "success": result["success"]},
    )
    return {
        "action": "create_user",
        "username": username,
        "success": result["success"],
        "error": result.get("error", ""),
        "rollback": f"yunohost user delete {username}" if result["success"] else None,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def delete_user(username: str, purge: bool = False) -> dict[str, Any]:
    """Delete a YunoHost user."""
    cmd = ["user", "delete", username]
    if purge:
        cmd.append("--purge")
    result = _ynh(cmd)
    _audit_log(
        "delete_user",
        {"username": username, "purge": purge, "success": result["success"]},
    )
    return {
        "action": "delete_user",
        "username": username,
        "success": result["success"],
        "error": result.get("error", ""),
        "rollback": "Recreate user manually or restore from backup",
        "timestamp": datetime.datetime.now().isoformat(),
    }


def add_domain(domain: str) -> dict[str, Any]:
    """Add a domain to YunoHost."""
    result = _ynh(["domain", "add", domain])
    _audit_log("add_domain", {"domain": domain, "success": result["success"]})
    return {
        "action": "add_domain",
        "domain": domain,
        "success": result["success"],
        "error": result.get("error", ""),
        "rollback": f"yunohost domain remove {domain}" if result["success"] else None,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def _listed_domains() -> set[str]:
    """Return the current YunoHost domain set when available."""

    result = _ynh(["domain", "list"])
    data = result.get("data", {}) if isinstance(result.get("data"), dict) else {}
    domains = data.get("domains", [])
    if not result.get("success") or not isinstance(domains, list):
        return set()
    return {str(item).strip() for item in domains if str(item).strip()}


def _prepare_blueprint_domains(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Ensure all blueprint target domains exist before installing apps."""

    existing_domains = _listed_domains()
    prepared_domains: list[dict[str, Any]] = []
    seen_targets: set[str] = set()

    for step in plan.get("app_plans", []):
        target_domain = str(step.get("target_domain", "")).strip()
        if not target_domain or target_domain in seen_targets:
            continue
        seen_targets.add(target_domain)
        if target_domain in existing_domains:
            prepared_domains.append(
                {
                    "domain": target_domain,
                    "created": False,
                    "success": True,
                    "error": "",
                }
            )
            continue

        result = _ynh(["domain", "add", target_domain])
        success = bool(result.get("success"))
        prepared_domains.append(
            {
                "domain": target_domain,
                "created": success,
                "success": success,
                "error": result.get("error", ""),
            }
        )
        if success:
            existing_domains.add(target_domain)

    return prepared_domains


def remove_domain(domain: str) -> dict[str, Any]:
    """Remove a domain from YunoHost."""
    result = _ynh(["domain", "remove", domain])
    _audit_log("remove_domain", {"domain": domain, "success": result["success"]})
    return {
        "action": "remove_domain",
        "domain": domain,
        "success": result["success"],
        "error": result.get("error", ""),
        "timestamp": datetime.datetime.now().isoformat(),
    }


def system_upgrade(apps: bool = False, system: bool = False) -> dict[str, Any]:
    """Apply system and/or app updates."""
    cmd = ["tools", "upgrade"]
    if apps:
        cmd.append("--apps")
    if system:
        cmd.append("--system")
    if not apps and not system:
        return {
            "action": "system_upgrade",
            "success": False,
            "error": "Specify apps=True and/or system=True",
        }
    result = _ynh(cmd, timeout=1800)
    _audit_log(
        "system_upgrade", {"apps": apps, "system": system, "success": result["success"]}
    )
    return {
        "action": "system_upgrade",
        "apps": apps,
        "system": system,
        "success": result["success"],
        "error": result.get("error", ""),
        "rollback": "Restore from backup if issues arise",
        "timestamp": datetime.datetime.now().isoformat(),
    }


def deploy_blueprint(
    blueprint_slug: str,
    domain: str,
    apps: list[str],
    subdomains: list[str] | None = None,
) -> dict[str, Any]:
    """Deploy a business blueprint by resolving an executable install plan first."""
    if resolve_blueprint_plan is None:
        return {
            "action": "deploy_blueprint",
            "blueprint": blueprint_slug,
            "domain": domain,
            "total_apps": len(apps),
            "installed": 0,
            "failed": len(apps),
            "results": [],
            "success": False,
            "error": "Blueprint deployment is unavailable in this repository profile",
            "timestamp": datetime.datetime.now().isoformat(),
        }
    blueprint = Blueprint(
        slug=blueprint_slug,
        name=blueprint_slug.replace("-", " ").title(),
        description="",
        activity=blueprint_slug,
        recommended_apps=apps,
        subdomains=subdomains or [],
    )
    plan = resolve_blueprint_plan(blueprint, domain)
    if not plan.get("allowed"):
        error = "; ".join(
            plan.get("blocking_issues", []) or [plan.get("status", "plan_failed")]
        )
        _audit_log(
            "deploy_blueprint_rejected",
            {
                "blueprint": blueprint_slug,
                "domain": domain,
                "total": len(apps),
                "success": False,
                "error": error,
            },
        )
        return {
            "action": "deploy_blueprint",
            "blueprint": blueprint_slug,
            "domain": domain,
            "total_apps": len(apps),
            "installed": 0,
            "failed": len(apps),
            "results": [],
            "success": False,
            "error": error,
            "warnings": plan.get("warnings", []),
            "plan": plan,
            "timestamp": datetime.datetime.now().isoformat(),
        }

    domain_results = _prepare_blueprint_domains(plan)
    failed_domains = [entry for entry in domain_results if not entry.get("success")]
    if failed_domains:
        failed_domain_names = ", ".join(entry["domain"] for entry in failed_domains)
        error = f"failed_to_prepare_domains:{failed_domain_names}"
        _audit_log(
            "deploy_blueprint_rejected",
            {
                "blueprint": blueprint_slug,
                "domain": domain,
                "total": len(apps),
                "success": False,
                "error": error,
            },
        )
        return {
            "action": "deploy_blueprint",
            "blueprint": blueprint_slug,
            "domain": domain,
            "total_apps": len(apps),
            "installed": 0,
            "failed": len(apps),
            "results": [],
            "success": False,
            "error": error,
            "warnings": plan.get("warnings", []),
            "plan": plan,
            "domains": domain_results,
            "timestamp": datetime.datetime.now().isoformat(),
        }

    results = []
    for step in plan.get("app_plans", []):
        r = install_app(step["app"], step["target_domain"], step["target_path"])
        results.append(
            {
                "app": step["app"],
                "domain": step["target_domain"],
                "path": step["target_path"],
                "success": r["success"],
                "error": r.get("error", ""),
            }
        )

    ok = sum(1 for r in results if r["success"])
    _audit_log(
        "deploy_blueprint",
        {
            "blueprint": blueprint_slug,
            "domain": domain,
            "total": len(apps),
            "success": ok,
        },
    )
    return {
        "action": "deploy_blueprint",
        "blueprint": blueprint_slug,
        "domain": domain,
        "total_apps": len(apps),
        "installed": ok,
        "failed": len(apps) - ok,
        "results": results,
        "success": ok == len(apps),
        "warnings": plan.get("warnings", []),
        "domains": domain_results,
        "plan": plan,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def get_admin_action_log(lines: int = 50) -> list[dict[str, Any]]:
    """Read the admin action audit log."""
    log_path = Path("/var/log/yunohost-mcp-server/admin-actions.log")
    if not log_path.exists():
        return []
    entries = []
    for line in log_path.read_text().strip().splitlines()[-lines:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries
