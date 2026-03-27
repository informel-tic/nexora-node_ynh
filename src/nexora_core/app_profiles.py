"""Application install profiles used to make automated YunoHost installs safer."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl

DEFAULT_APP_PROFILES: dict[str, dict[str, Any]] = {
    "nextcloud": {
        "display_name": "Nextcloud",
        "automation": "supported",
        "install_mode": "domain_path",
        "safe_defaults": {"path": "/"},
        "allowed_extra_args": [],
        "notes": ["Supports standard domain/path installs through Nexora automation."],
    },
    "roundcube": {
        "display_name": "Roundcube",
        "automation": "supported",
        "install_mode": "domain_path",
        "safe_defaults": {"path": "/webmail"},
        "allowed_extra_args": [],
        "notes": ["Webmail profile with a dedicated default path."],
    },
    "vaultwarden": {
        "display_name": "Vaultwarden",
        "automation": "supported",
        "install_mode": "subdomain_preferred",
        "safe_defaults": {"path": "/"},
        "allowed_extra_args": [],
        "notes": ["Best deployed on a dedicated subdomain to keep secrets isolated."],
    },
    "wordpress": {
        "display_name": "WordPress",
        "automation": "supported",
        "install_mode": "domain_path",
        "safe_defaults": {"path": "/"},
        "allowed_extra_args": [],
        "notes": ["CMS profile using the standard domain/path contract."],
    },
    "wikijs": {
        "display_name": "Wiki.js",
        "automation": "supported",
        "install_mode": "domain_path",
        "safe_defaults": {"path": "/wiki"},
        "allowed_extra_args": [],
        "notes": ["Collaboration wiki with a non-root default path."],
    },
    "hedgedoc": {
        "display_name": "HedgeDoc",
        "automation": "supported",
        "install_mode": "domain_path",
        "safe_defaults": {"path": "/docs"},
        "allowed_extra_args": [],
        "notes": ["Collaborative notes profile with a dedicated default path."],
    },
    "jitsi": {
        "display_name": "Jitsi Meet",
        "automation": "supported",
        "install_mode": "subdomain_only",
        "safe_defaults": {"path": "/"},
        "allowed_extra_args": [],
        "notes": [
            "Requires the root path on a dedicated subdomain for predictable routing."
        ],
    },
    "mattermost": {
        "display_name": "Mattermost",
        "automation": "supported",
        "install_mode": "subdomain_only",
        "safe_defaults": {"path": "/"},
        "allowed_extra_args": [],
        "notes": ["Team messaging profile requiring a root-path deployment."],
    },
}


class AppProfileError(ValueError):
    """Raised when an install request does not match a supported profile."""


def list_app_profiles() -> list[dict[str, Any]]:
    """Return the sorted list of supported app profiles."""

    return [resolve_app_profile(app_id) for app_id in sorted(DEFAULT_APP_PROFILES)]


def resolve_app_profile(app_id: str) -> dict[str, Any]:
    """Return a normalized install profile for an application."""

    profile = DEFAULT_APP_PROFILES.get(app_id)
    if profile is None:
        raise AppProfileError(
            f"App '{app_id}' is not yet covered by a Nexora automation profile. "
            "Use catalog inspection/manual review before automating installation."
        )
    normalized = dict(profile)
    normalized["app_id"] = app_id
    normalized.setdefault("safe_defaults", {})
    normalized.setdefault("allowed_extra_args", [])
    normalized.setdefault("notes", [])
    return normalized


def _normalize_path(path: str | None, profile: dict[str, Any]) -> str:
    candidate = (path or "").strip() or str(
        profile.get("safe_defaults", {}).get("path", "/")
    )
    if not candidate.startswith("/"):
        raise AppProfileError(f"Install path must start with '/': {candidate}")
    return candidate.rstrip("/") or "/"


def _parse_args(args: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for key, value in parse_qsl(args, keep_blank_values=True):
        if not key:
            raise AppProfileError("Install args contain an empty key")
        parsed[key] = value
    if args.strip() and not parsed and "=" not in args:
        raise AppProfileError(
            "Install args must use query-string format like key=value&key2=value2"
        )
    return parsed


def validate_install_request(
    app_id: str, domain: str, path: str = "/", args: str = ""
) -> dict[str, Any]:
    """Validate and normalize an automated install request against the app profile."""

    profile = resolve_app_profile(app_id)
    normalized_domain = domain.strip()
    if not normalized_domain:
        raise AppProfileError("Domain is required for automated installs")

    normalized_path = _normalize_path(path, profile)
    normalized_args = _parse_args(args)
    allowed_extra_args = {
        str(item).strip()
        for item in profile.get("allowed_extra_args", [])
        if str(item).strip()
    }
    unexpected_args = sorted(set(normalized_args) - allowed_extra_args)
    if unexpected_args:
        raise AppProfileError(
            f"App '{app_id}' does not allow automated extra args: {', '.join(unexpected_args)}"
        )

    warnings: list[str] = []
    install_mode = str(profile.get("install_mode", "domain_path"))
    if install_mode == "subdomain_only" and normalized_path != "/":
        raise AppProfileError(
            f"App '{app_id}' requires a dedicated subdomain and the root path '/'"
        )
    if install_mode == "subdomain_preferred" and normalized_path != "/":
        warnings.append("profile_prefers_root_path_on_dedicated_subdomain")

    return {
        "app_id": app_id,
        "profile": profile,
        "domain": normalized_domain,
        "path": normalized_path,
        "args": normalized_args,
        "args_string": "&".join(
            f"{key}={value}" for key, value in normalized_args.items()
        ),
        "warnings": warnings,
    }
