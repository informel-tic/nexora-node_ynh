from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml as _yaml  # type: ignore
except Exception:  # pragma: no cover - fallback in limited environments
    _yaml = None

from .app_profiles import AppProfileError, resolve_app_profile
from .compatibility import _simple_yaml_load
from .models import Blueprint
from .preflight import build_install_preflight


def _list_field(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key, [])
    return value if isinstance(value, list) else []


def _dict_field(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def load_blueprints(root: str | Path) -> list[Blueprint]:
    root = Path(root)
    items: list[Blueprint] = []
    if not root.exists():
        return items
    for profile in sorted(root.glob("*/profile.yaml")):
        raw = profile.read_text()
        data = (
            _yaml.safe_load(raw)
            if _yaml is not None
            else (_simple_yaml_load(raw) or {})
        )
        data = data if isinstance(data, dict) else {}
        items.append(
            Blueprint(
                slug=data.get("slug", profile.parent.name),
                name=data.get("name", profile.parent.name.replace("-", " ").title()),
                description=data.get("description", ""),
                activity=data.get("activity", profile.parent.name),
                profiles=_list_field(data, "profiles"),
                recommended_apps=_list_field(data, "recommended_apps"),
                subdomains=_list_field(data, "subdomains"),
                security_baseline=_dict_field(data, "security_baseline"),
                monitoring_baseline=_list_field(data, "monitoring_baseline"),
                pra_baseline=_list_field(data, "pra_baseline"),
                portal=_dict_field(data, "portal"),
            )
        )
    return items


def resolve_blueprint(root: str | Path, slug: str) -> Blueprint | None:
    """Load a single blueprint by slug."""

    return next((bp for bp in load_blueprints(root) if bp.slug == slug), None)


def _blueprint_target_domain(
    domain: str, subdomains: list[str], index: int
) -> tuple[str, str]:
    subdomain = subdomains[index] if index < len(subdomains) else ""
    target_domain = f"{subdomain}.{domain}" if subdomain else domain
    return target_domain, subdomain


def resolve_blueprint_plan(blueprint: Blueprint, domain: str) -> dict[str, Any]:
    """Resolve a blueprint into an executable install plan with per-app preflights."""

    app_plans: list[dict[str, Any]] = []
    warnings: list[str] = []
    blocking_issues: list[str] = []
    manual_review_required = False

    for index, app_id in enumerate(blueprint.recommended_apps):
        target_domain, subdomain = _blueprint_target_domain(
            domain, blueprint.subdomains, index
        )
        try:
            profile = resolve_app_profile(app_id)
        except AppProfileError as exc:
            app_plan = {
                "step": index + 1,
                "app": app_id,
                "target_domain": target_domain,
                "target_path": "/",
                "profile": {"app_id": app_id, "automation": "manual_review_required"},
                "subdomain": subdomain,
                "warnings": [],
                "blocking_issues": [str(exc)],
                "manual_review_required": True,
                "preflight": {},
            }
            app_plans.append(app_plan)
            blocking_issues.append(f"app:{app_id}")
            manual_review_required = True
            continue

        target_path = "/"
        app_warnings: list[str] = []
        app_blocking: list[str] = []
        install_mode = str(profile.get("install_mode", "domain_path"))
        default_path = str(profile.get("safe_defaults", {}).get("path", "/"))

        if install_mode == "subdomain_only":
            if not subdomain:
                app_blocking.append(
                    "missing_blueprint_subdomain_for_subdomain_only_profile"
                )
            target_path = "/"
        elif subdomain:
            target_path = "/"
        else:
            target_path = default_path
            if install_mode == "subdomain_preferred":
                app_warnings.append("profile_prefers_dedicated_subdomain")

        preflight = build_install_preflight(app_id, target_domain, target_path)
        if preflight.get("warnings"):
            app_warnings.extend(preflight["warnings"])
        if preflight.get("blocking_issues"):
            app_blocking.extend(preflight["blocking_issues"])
        if preflight.get("manual_review_required"):
            manual_review_required = True

        app_plan = {
            "step": index + 1,
            "app": app_id,
            "target_domain": target_domain,
            "target_path": target_path,
            "profile": profile,
            "subdomain": subdomain,
            "warnings": sorted(set(app_warnings)),
            "blocking_issues": sorted(set(app_blocking)),
            "manual_review_required": bool(preflight.get("manual_review_required"))
            or bool(app_blocking and not preflight.get("allowed", False)),
            "preflight": preflight,
        }
        app_plans.append(app_plan)

        warnings.extend(app_plan["warnings"])
        if app_plan["blocking_issues"]:
            blocking_issues.append(f"app:{app_id}")

    status = (
        "blocked"
        if blocking_issues
        else "manual_review_required"
        if manual_review_required
        else "ready"
    )
    return {
        "blueprint": blueprint.slug,
        "name": blueprint.name,
        "domain": domain,
        "allowed": status == "ready",
        "status": status,
        "manual_review_required": manual_review_required,
        "warnings": sorted(set(warnings)),
        "blocking_issues": blocking_issues,
        "app_plans": app_plans,
        "topology": [
            {
                "app": plan["app"],
                "domain": plan["target_domain"],
                "path": plan["target_path"],
                "subdomain": plan["subdomain"],
            }
            for plan in app_plans
        ],
    }
