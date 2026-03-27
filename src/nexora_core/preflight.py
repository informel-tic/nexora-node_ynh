"""Unified mutation preflight checks for Nexora admin actions."""

from __future__ import annotations

from typing import Any

from .app_profiles import AppProfileError, validate_install_request
from .compatibility import assess_compatibility, load_compatibility_matrix
try:
    from . import yh_adapter
except ImportError:  # pragma: no cover - absent in nexora-saas split
    yh_adapter = None  # type: ignore[assignment]


def _local_yunohost_version() -> str | None:
    if yh_adapter is None:
        return None
    version_data = yh_adapter.ynh_version()
    if isinstance(version_data, dict):
        yunohost = version_data.get("yunohost", {})
        if isinstance(yunohost, dict):
            version = str(yunohost.get("version", "")).strip()
            return version or None
    return None


def _domain_map(domain: str | None) -> dict[str, Any]:
    if yh_adapter is None:
        return {}
    app_map = yh_adapter.ynh_app_map()
    if not domain or not isinstance(app_map, dict):
        return {}
    scoped = app_map.get(domain, {})
    return scoped if isinstance(scoped, dict) else {}


def _backup_archives() -> list[Any]:
    if yh_adapter is None:
        return []
    backups = yh_adapter.ynh_backups()
    if isinstance(backups, dict):
        archives = backups.get("archives", [])
        if isinstance(archives, list):
            return archives
    return []


def _unhealthy_services() -> list[str]:
    if yh_adapter is None:
        return []
    services = yh_adapter.ynh_services()
    unhealthy: list[str] = []
    if not isinstance(services, dict):
        return unhealthy
    for name, status in (services.get("services", {}) or {}).items():
        if isinstance(status, dict):
            raw = str(status.get("status", "")).lower()
            if raw and raw not in {"running", "enabled", "unknown"}:
                unhealthy.append(name)
    return sorted(unhealthy)


def _public_permissions() -> list[str]:
    if yh_adapter is None:
        return []
    permissions = yh_adapter.ynh_permissions()
    exposed: list[str] = []
    if not isinstance(permissions, dict):
        return exposed
    for name, perm in (permissions.get("permissions", {}) or {}).items():
        if isinstance(perm, dict) and "visitors" in perm.get("allowed", []):
            exposed.append(name)
    return sorted(exposed)


def _compatibility_report(capability: str) -> dict[str, Any]:
    compatibility = assess_compatibility(
        "2.0.0", _local_yunohost_version(), matrix=load_compatibility_matrix()
    )
    verdict = (
        compatibility.get("capability_verdicts", {}).get(capability, {})
        if isinstance(compatibility.get("capability_verdicts"), dict)
        else {}
    )
    return {"compatibility": compatibility, "verdict": verdict}


def _status_for(blocking_issues: list[str], manual_review_required: bool) -> str:
    if blocking_issues:
        return "blocked"
    if manual_review_required:
        return "manual_review_required"
    return "allowed"


def build_install_preflight(
    app_id: str, domain: str, path: str = "/", args: str = ""
) -> dict[str, Any]:
    """Validate whether an automated app install is currently safe to attempt."""

    report: dict[str, Any] = {
        "action": "install_app",
        "app": app_id,
        "domain": domain,
        "path": path,
        "allowed": False,
        "status": "blocked",
        "warnings": [],
        "blocking_issues": [],
        "manual_review_required": False,
        "suggested_changes": [],
        "rollback_prereqs": [],
        "profile": None,
        "compatibility": {},
    }

    try:
        request = validate_install_request(app_id, domain, path, args)
    except AppProfileError as exc:
        report["blocking_issues"].append(str(exc))
        report["status"] = "blocked"
        return report

    report["domain"] = request["domain"]
    report["path"] = request["path"]
    report["warnings"].extend(request.get("warnings", []))
    report["profile"] = request["profile"]
    report["normalized_request"] = request

    compatibility_report = _compatibility_report("install_app")
    report["compatibility"] = compatibility_report["compatibility"]
    verdict = (
        compatibility_report["verdict"]
        if isinstance(compatibility_report["verdict"], dict)
        else {}
    )
    if not verdict.get("allowed"):
        reasons = ", ".join(verdict.get("reasons", []) or ["capability_not_allowed"])
        report["blocking_issues"].append(f"compatibility:{reasons}")
    if verdict.get("requires_manual_review"):
        report["manual_review_required"] = True

    domain_map = _domain_map(request["domain"])
    if request["path"] in domain_map:
        current = domain_map.get(request["path"])
        report["blocking_issues"].append(
            f"path_already_used:{request['domain']}{request['path']}->{current}"
        )
        suggested_path = f"{request['path'].rstrip('/') or '/app'}-1"
        report["suggested_changes"].append(
            {"path": suggested_path, "reason": "avoid_existing_path_collision"}
        )

    backups = _backup_archives()
    if not backups:
        report["warnings"].append("no_backup_detected")
        report["rollback_prereqs"].append("create_backup_before_install")
    else:
        report["rollback_prereqs"].append("ensure_recent_backup_reference")

    unhealthy_services = _unhealthy_services()
    if unhealthy_services:
        report["warnings"].append(f"unhealthy_services:{','.join(unhealthy_services)}")

    public_permissions = _public_permissions()
    if public_permissions:
        report["warnings"].append(f"public_permissions:{','.join(public_permissions)}")

    report["status"] = _status_for(
        report["blocking_issues"], report["manual_review_required"]
    )
    report["allowed"] = report["status"] == "allowed"
    return report


def build_upgrade_preflight(app_id: str = "") -> dict[str, Any]:
    """Validate whether an app upgrade is currently safe to attempt."""

    report: dict[str, Any] = {
        "action": "upgrade_app",
        "app": app_id or "all",
        "allowed": False,
        "status": "blocked",
        "warnings": [],
        "blocking_issues": [],
        "manual_review_required": False,
        "suggested_changes": [],
        "rollback_prereqs": [],
        "compatibility": {},
    }

    compatibility_report = _compatibility_report("upgrade_app")
    report["compatibility"] = compatibility_report["compatibility"]
    verdict = (
        compatibility_report["verdict"]
        if isinstance(compatibility_report["verdict"], dict)
        else {}
    )
    if not verdict.get("allowed"):
        reasons = ", ".join(verdict.get("reasons", []) or ["capability_not_allowed"])
        report["blocking_issues"].append(f"compatibility:{reasons}")
    if verdict.get("requires_manual_review"):
        report["manual_review_required"] = True

    backups = _backup_archives()
    if not backups:
        report["blocking_issues"].append("pre_upgrade_backup_required")
        report["rollback_prereqs"].append("create_backup_before_upgrade")
    else:
        report["rollback_prereqs"].append("ensure_pre_upgrade_backup_is_identified")

    unhealthy_services = _unhealthy_services()
    if unhealthy_services:
        report["warnings"].append(f"unhealthy_services:{','.join(unhealthy_services)}")

    report["status"] = _status_for(
        report["blocking_issues"], report["manual_review_required"]
    )
    report["allowed"] = report["status"] == "allowed"
    return report


def build_blueprint_preflight(
    blueprint_slug: str, domain: str, apps: list[str]
) -> dict[str, Any]:
    """Validate whether a blueprint deployment is currently safe to attempt."""

    report: dict[str, Any] = {
        "action": "deploy_blueprint",
        "blueprint": blueprint_slug,
        "domain": domain,
        "apps": apps,
        "allowed": False,
        "status": "blocked",
        "warnings": [],
        "blocking_issues": [],
        "manual_review_required": False,
        "suggested_changes": [],
        "rollback_prereqs": [],
        "compatibility": {},
        "app_reports": [],
    }

    compatibility_report = _compatibility_report("deploy_blueprint")
    report["compatibility"] = compatibility_report["compatibility"]
    verdict = (
        compatibility_report["verdict"]
        if isinstance(compatibility_report["verdict"], dict)
        else {}
    )
    if not verdict.get("allowed"):
        reasons = ", ".join(verdict.get("reasons", []) or ["capability_not_allowed"])
        report["blocking_issues"].append(f"compatibility:{reasons}")
    if verdict.get("requires_manual_review"):
        report["manual_review_required"] = True

    for app_id in apps:
        app_report = build_install_preflight(app_id, domain, "/")
        report["app_reports"].append(app_report)
        report["warnings"].extend(app_report.get("warnings", []))
        report["rollback_prereqs"].extend(app_report.get("rollback_prereqs", []))
        report["suggested_changes"].extend(app_report.get("suggested_changes", []))
        if app_report.get("blocking_issues"):
            report["blocking_issues"].append(f"app:{app_id}")
        if app_report.get("manual_review_required"):
            report["manual_review_required"] = True

    report["warnings"] = sorted(set(report["warnings"]))
    report["rollback_prereqs"] = sorted(set(report["rollback_prereqs"]))
    report["status"] = _status_for(
        report["blocking_issues"], report["manual_review_required"]
    )
    report["allowed"] = report["status"] == "allowed"
    return report
