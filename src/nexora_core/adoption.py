from __future__ import annotations
from typing import Any


_CERT_OK_STYLES = {"success", "ok", "valid", "great"}
_BLOCKING_COLLISION_TYPES = {
    "missing-domain",
    "path-already-used",
    "path-prefix-conflict",
    "nginx-unhealthy",
}


def _normalized_path(path: str | None) -> str | None:
    if path is None:
        return None
    normalized = path.strip() or "/"
    return normalized if normalized.startswith("/") else f"/{normalized}"


def _domain_map(inventory: dict[str, Any], domain: str | None) -> dict[str, Any]:
    app_map = (
        inventory.get("app_map", {})
        if isinstance(inventory.get("app_map"), dict)
        else {}
    )
    if not domain or not isinstance(app_map, dict):
        return {}
    dm = app_map.get(domain, {})
    return dm if isinstance(dm, dict) else {}


def suggest_path(
    inventory: dict[str, Any], requested_domain: str | None, requested_path: str | None
) -> str | None:
    normalized_path = _normalized_path(requested_path)
    if not requested_domain or not normalized_path:
        return requested_path
    domain_map = _domain_map(inventory, requested_domain)
    if normalized_path not in domain_map:
        return normalized_path
    base = normalized_path.rstrip("/") or "/nexora"
    i = 1
    while True:
        candidate = f"{base}-{i}"
        if candidate not in domain_map:
            return candidate
        i += 1


def build_adoption_report(
    inventory: dict[str, Any],
    requested_domain: str | None = None,
    requested_path: str | None = None,
) -> dict[str, Any]:
    apps = (
        inventory.get("apps", {}).get("apps", [])
        if isinstance(inventory.get("apps"), dict)
        else []
    )
    domains = (
        inventory.get("domains", {}).get("domains", [])
        if isinstance(inventory.get("domains"), dict)
        else []
    )
    certificates = (
        inventory.get("certs", {}).get("certificates", {})
        if isinstance(inventory.get("certs"), dict)
        else {}
    )
    permissions = (
        inventory.get("permissions", {}).get("permissions", {})
        if isinstance(inventory.get("permissions"), dict)
        else {}
    )
    services = (
        inventory.get("services", {}).get("services", {})
        if isinstance(inventory.get("services"), dict)
        else {}
    )
    backups = (
        inventory.get("backups", {}).get("archives", [])
        if isinstance(inventory.get("backups"), dict)
        else []
    )
    normalized_path = _normalized_path(requested_path)
    collisions: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if requested_domain and requested_domain not in domains:
        collisions.append({"type": "missing-domain", "domain": requested_domain})

    domain_map = _domain_map(inventory, requested_domain)
    if requested_domain and normalized_path and normalized_path in domain_map:
        collisions.append(
            {
                "type": "path-already-used",
                "domain": requested_domain,
                "path": normalized_path,
                "current": domain_map.get(normalized_path),
            }
        )

    if requested_domain and normalized_path and isinstance(domain_map, dict):
        requested_prefix = normalized_path.rstrip("/")
        for existing_path, current in domain_map.items():
            if not isinstance(existing_path, str):
                continue
            existing_prefix = existing_path.rstrip("/")
            if not requested_prefix or not existing_prefix:
                continue
            if existing_prefix == requested_prefix:
                continue
            if existing_prefix.startswith(
                f"{requested_prefix}/"
            ) or requested_prefix.startswith(f"{existing_prefix}/"):
                collisions.append(
                    {
                        "type": "path-prefix-conflict",
                        "domain": requested_domain,
                        "path": normalized_path,
                        "current_path": existing_path,
                        "current": current,
                    }
                )
                break

    if isinstance(services.get("nginx"), dict):
        nginx_status = str(services["nginx"].get("status", "")).lower()
        if nginx_status and nginx_status not in {"running", "enabled", "unknown"}:
            collisions.append({"type": "nginx-unhealthy", "status": nginx_status})

    if requested_domain:
        cert_data = (
            certificates.get(requested_domain)
            if isinstance(certificates, dict)
            else None
        )
        if cert_data is None:
            warnings.append(
                {"type": "missing-domain-certificate", "domain": requested_domain}
            )
        elif isinstance(cert_data, dict):
            cert_style = str(cert_data.get("style", "")).lower()
            if cert_style and cert_style not in _CERT_OK_STYLES:
                warnings.append(
                    {
                        "type": "certificate-not-ready",
                        "domain": requested_domain,
                        "style": cert_style,
                    }
                )

    public_apps = []
    for name, perm in permissions.items():
        if isinstance(perm, dict) and "visitors" in perm.get("allowed", []):
            public_apps.append(name)

    unhealthy_services = []
    for name, status in services.items():
        if isinstance(status, dict):
            raw = str(status.get("status", "")).lower()
            if raw and raw not in {"running", "enabled", "unknown"}:
                unhealthy_services.append(name)

    if len(apps) == 0:
        mode = "fresh"
    elif any(
        c["type"] in {"path-already-used", "path-prefix-conflict"} for c in collisions
    ):
        mode = "adopt"
    else:
        mode = "augment"

    notes = [
        "Run Nexora in observe-only mode first on populated instances.",
        "Keep existing apps, domains and permissions untouched until reviewed.",
        "Import the current state before enabling fleet-wide synchronization.",
    ]
    if not backups:
        notes.append(
            "No YunoHost backup detected: create a backup before installation."
        )
    if public_apps:
        notes.append(
            "Some apps are exposed to visitors: review the security posture before augmenting."
        )
    if unhealthy_services:
        notes.append("Some services are not fully healthy: fix them before augmenting.")
    if warnings:
        notes.append(
            "Additional infra warnings detected (certificate/path hygiene); review the adoption report details."
        )

    blocking_collisions = [
        c for c in collisions if c.get("type") in _BLOCKING_COLLISION_TYPES
    ]

    return {
        "recommended_mode": mode,
        "existing_apps_count": len(apps),
        "existing_domains_count": len(domains),
        "public_permissions": public_apps,
        "unhealthy_services": unhealthy_services,
        "collisions": collisions,
        "blocking_collisions": blocking_collisions,
        "warnings": warnings,
        "safe_to_install": len(blocking_collisions) == 0,
        "suggested_path": suggest_path(inventory, requested_domain, normalized_path),
        "notes": notes,
    }
