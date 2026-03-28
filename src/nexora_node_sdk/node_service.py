"""Lightweight service for the Nexora node agent.

NodeService provides local inventory, identity, and compatibility
without importing any SaaS-specific modules (fleet, governance,
enrollment issuance, quotas, etc.).
"""

from __future__ import annotations

import socket
import time
import logging
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .blueprints import load_blueprints
from .compatibility import (
    assess_compatibility,
    load_compatibility_matrix,
    resolve_compatibility_matrix_path,
)
from .identity import (
    NEXORA_IDENTITY,
    generate_fleet_id,
    generate_node_credentials,
    generate_node_id,
)
from .models import NodeSummary
from .operator_actions import summarize_agent_capabilities
from .persistence import build_state_repository
from .scoring import compute_health_score, compute_pra_score, compute_security_score
from .state import normalize_node_record
from . import yh_adapter
from .version import NEXORA_VERSION

logger = logging.getLogger(__name__)


class _InventoryCache:
    """Per-section cache with a configurable TTL (default 30s)."""

    def __init__(self, ttl: float = 30.0):
        self.ttl = ttl
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > self.ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)


_SECTION_FETCHERS: dict[str, Any] = {
    "version": yh_adapter.ynh_version,
    "settings": yh_adapter.ynh_settings,
    "apps": yh_adapter.ynh_apps,
    "domains": yh_adapter.ynh_domains,
    "certs": yh_adapter.ynh_certs,
    "services": yh_adapter.ynh_services,
    "backups": yh_adapter.ynh_backups,
    "app_map": yh_adapter.ynh_app_map,
    "permissions": yh_adapter.ynh_permissions,
    "diagnosis": yh_adapter.ynh_diagnosis,
}


def _parse_cached_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class NodeService:
    """Lightweight service for the node agent.

    Provides local inventory, identity, and compatibility — no fleet,
    governance, enrollment issuance, or multi-tenant orchestration.
    """

    def __init__(self, repo_root: str | Path, state_path: str | Path | None = None):
        self.repo_root = Path(repo_root)
        self.state = build_state_repository(
            state_path or self.repo_root / "var" / "state.json"
        )
        self._cache = _InventoryCache(ttl=30.0)

    def list_blueprints(self):
        return load_blueprints(self.repo_root / "blueprints")

    def _load_persisted_cache_entry(self, section: str) -> Any | None:
        state = self.state.load()
        entry = state.get("inventory_cache", {}).get(section)
        if not isinstance(entry, dict):
            return None
        cached_at = _parse_cached_at(entry.get("cached_at"))
        if cached_at is None:
            return None
        age = (datetime.now(timezone.utc) - cached_at).total_seconds()
        if age > self._cache.ttl:
            return None
        value = entry.get("value")
        self._cache.set(section, value)
        return value

    def _persist_cache_entry(self, section: str, value: Any) -> None:
        state = self.state.load()
        cache = state.setdefault("inventory_cache", {})
        cache[section] = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "value": value,
        }
        self.state.save(state)

    def _fetch_section(self, section: str) -> Any:
        cached = self._cache.get(section)
        if cached is not None:
            return cached
        persisted = self._load_persisted_cache_entry(section)
        if persisted is not None:
            return persisted
        fetcher = _SECTION_FETCHERS.get(section)
        if fetcher is None:
            return {
                "_error": f"unknown section: {section}",
                "available_sections": list(_SECTION_FETCHERS),
            }
        value = fetcher()
        self._cache.set(section, value)
        self._persist_cache_entry(section, value)
        return value

    def local_inventory(self) -> dict[str, Any]:
        return {key: self._fetch_section(key) for key in _SECTION_FETCHERS}

    def inventory_slice(self, section: str) -> dict[str, Any]:
        return self._fetch_section(section)

    def invalidate_cache(self, section: str | None = None) -> None:
        self._cache.invalidate(section)
        state = self.state.load()
        cache = state.setdefault("inventory_cache", {})
        if section is None:
            cache.clear()
        else:
            cache.pop(section, None)
        self.state.save(state)

    def _local_versions(self) -> tuple[str, str | None, str | None]:
        nexora_version = NEXORA_VERSION
        version_data = self._fetch_section("version")
        ynh_version = (
            version_data.get("yunohost", {}).get("version")
            if isinstance(version_data, dict)
            else None
        )
        debian_version = None
        os_release = Path("/etc/os-release")
        if os_release.exists():
            data = {}
            for line in os_release.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    data[key] = value.strip().strip('"')
            debian_version = data.get("VERSION_ID")
        return nexora_version, ynh_version, debian_version

    def compatibility_report(self) -> dict[str, Any]:
        nexora_version, ynh_version, _ = self._local_versions()
        matrix_path = resolve_compatibility_matrix_path(self.repo_root)
        matrix = load_compatibility_matrix(
            matrix_path if matrix_path.exists() else None
        )
        assessment = assess_compatibility(nexora_version, ynh_version, matrix=matrix)
        return {"matrix": matrix, "assessment": assessment}

    def _ensure_identity_state(
        self, state: dict[str, Any], *, enrolled_by: str | None = None
    ) -> dict[str, Any]:
        state.setdefault("identity", deepcopy(NEXORA_IDENTITY))
        state.setdefault(
            "branding",
            {
                "brand_name": NEXORA_IDENTITY["brand_name"],
                "accent": NEXORA_IDENTITY["accent"],
                "portal_title": NEXORA_IDENTITY["console_title"],
                "tagline": NEXORA_IDENTITY["tagline"],
                "sections": ["apps", "security", "monitoring", "pra", "fleet"],
            },
        )
        state.setdefault("fleet", {}).setdefault("managed_nodes", [])
        state["fleet"]["fleet_id"] = generate_fleet_id(state["fleet"].get("fleet_id"))

        identity = state["identity"]
        hostname = socket.gethostname()
        node_id = identity.get("node_id") or generate_node_id(hostname)
        identity["node_id"] = node_id
        identity["fleet_id"] = state["fleet"]["fleet_id"]
        identity["credential_type"] = "token+key"
        identity["enrolled_by"] = (
            enrolled_by or identity.get("enrolled_by") or "local-bootstrap"
        )
        identity["enrollment_modes"] = {
            "push": "Bootstrap initié depuis le control-plane vers le nœud cible.",
            "pull": "Bootstrap initié sur le nœud, puis enregistrement auprès du control-plane.",
        }
        if not identity.get("token_id"):
            credentials = generate_node_credentials(
                node_id, state["fleet"]["fleet_id"], self.state.path.parent / "certs"
            )
            identity.update(credentials)
        return state

    def local_node_summary(self) -> NodeSummary:
        _version_data = self._fetch_section("version")
        apps_data = self._fetch_section("apps")
        domains_data = self._fetch_section("domains")
        certs_data = self._fetch_section("certs")
        backups_data = self._fetch_section("backups")
        permissions_data = self._fetch_section("permissions")

        nexora_version, ynh_version, debian_version = self._local_versions()
        apps = apps_data.get("apps", []) if isinstance(apps_data, dict) else []
        domains = (
            domains_data.get("domains", []) if isinstance(domains_data, dict) else []
        )
        certs = (
            certs_data.get("certificates", {}) if isinstance(certs_data, dict) else {}
        )
        backups = (
            backups_data.get("archives", []) if isinstance(backups_data, dict) else []
        )
        permissions = (
            permissions_data.get("permissions", {})
            if isinstance(permissions_data, dict)
            else {}
        )
        _public_apps = [
            name
            for name, perm in permissions.items()
            if isinstance(perm, dict) and "visitors" in perm.get("allowed", [])
        ]

        inv = self.local_inventory()
        sec_report = compute_security_score(inv)
        pra_report = compute_pra_score(inv)
        health_report = compute_health_score(inv)

        notes = []
        if ynh_version:
            notes.append(f"YunoHost {ynh_version}")
        matrix_path = resolve_compatibility_matrix_path(self.repo_root)
        compatibility = assess_compatibility(
            nexora_version,
            ynh_version,
            matrix=load_compatibility_matrix(
                matrix_path if matrix_path.exists() else None
            ),
        )
        if compatibility.get("overall_status"):
            notes.append(f"compatibility-status:{compatibility['overall_status']}")
        if compatibility["reasons"]:
            notes.append("compatibility:" + ",".join(compatibility["reasons"]))
        if compatibility.get("manual_review_required"):
            notes.append("compatibility:manual_review_required")

        for detail in sec_report.get("details", []):
            if detail.get("severity") == "critical":
                notes.append(
                    f"security-critical:{detail.get('type')}:{detail.get('name', detail.get('domain', ''))}"
                )

        certs_ok = 0
        for _, data in certs.items():
            if isinstance(data, dict) and (
                str(data.get("style", "")).lower() in {"success", "ok"}
                or int(data.get("validity", 0) or 0) > 0
            ):
                certs_ok += 1

        state = self.state.load()
        state = self._ensure_identity_state(state)
        identity = state.get("identity") if isinstance(state, dict) else {}
        if not isinstance(identity, dict):
            identity = {}
        hostname = socket.gethostname()
        node_id = str(identity.get("node_id") or hostname)
        status = "healthy" if compatibility["bootstrap_allowed"] else "degraded"
        now = datetime.now(timezone.utc).isoformat()
        summary = NodeSummary(
            node_id=node_id,
            hostname=hostname,
            status=status,
            enrollment_mode="pull",
            yunohost_version=ynh_version,
            ynh_version=ynh_version,
            debian_version=debian_version,
            agent_version=nexora_version,
            last_seen=now,
            last_inventory_at=now,
            enrolled_by=identity.get("enrolled_by"),
            token_id=identity.get("token_id"),
            apps_count=len(apps),
            domains_count=len(domains),
            certs_ok=certs_ok,
            backups_count=len(backups),
            health_score=health_report["score"],
            pra_score=pra_report["score"],
            security_score=sec_report["score"],
            notes=notes,
            allowed_transitions=["degraded", "draining", "revoked", "retired"]
            if status == "healthy"
            else ["healthy", "draining", "revoked", "retired"],
            capabilities=summarize_agent_capabilities(),
        )
        return summary

    def identity(self) -> dict[str, Any]:
        state = self._ensure_identity_state(self.state.load())
        self.state.save(state)
        return state["identity"]

    def branding_profile(self, slug: str | None = None) -> dict[str, Any]:
        state = self.state.load()
        return state.get("branding", {})
