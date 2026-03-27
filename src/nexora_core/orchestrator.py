"""Application service orchestrating inventory, enrollment and fleet state."""

from __future__ import annotations

import socket
import time
import logging
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adoption import build_adoption_report
from .compatibility import (
    assess_compatibility,
    load_compatibility_matrix,
    resolve_compatibility_matrix_path,
)
from .enrollment import attest_node, consume_enrollment_token, issue_enrollment_token
from .identity import (
    NEXORA_IDENTITY,
    generate_fleet_id,
    generate_node_credentials,
    generate_node_id,
)
from .domain_models import (
    DashboardSummary,
    FleetSummary,
    NodeRecord,
    NodeSummary,
    TenantTier,
)
from .node_lifecycle import apply_lifecycle_action
from .operator_actions import summarize_agent_capabilities
from .persistence import build_state_repository
from .scoring import compute_health_score, compute_pra_score, compute_security_score
from .state import normalize_node_record, transition_node_status
from .version import NEXORA_VERSION

# --- Layer-specific imports (lazy) -------------------------------------------
# These modules may not be present in single-layer repositories after the split.
# SaaS-only: blueprints, quotas | Node-only: yh_adapter
try:
    from .blueprints import load_blueprints
except ImportError:  # pragma: no cover – absent in nexora-node_ynh
    load_blueprints = None  # type: ignore[assignment,misc]

try:
    from .quotas import is_quota_exceeded, get_quota_limit, get_tenant_entitlements
except ImportError:  # pragma: no cover – absent in nexora-node_ynh
    is_quota_exceeded = None  # type: ignore[assignment]
    get_quota_limit = None  # type: ignore[assignment]
    get_tenant_entitlements = None  # type: ignore[assignment]

try:
    from . import yh_adapter
except ImportError:  # pragma: no cover – absent in nexora-saas
    yh_adapter = None  # type: ignore[assignment]

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


# Populated only when yh_adapter is available (i.e. on a real YunoHost node).
if yh_adapter is not None:
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
else:
    _SECTION_FETCHERS: dict[str, Any] = {}  # type: ignore[no-redef]


def _parse_cached_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class NexoraService:
    def __init__(self, repo_root: str | Path, state_path: str | Path | None = None):
        self.repo_root = Path(repo_root)
        self.state = build_state_repository(
            state_path or self.repo_root / "var" / "state.json"
        )
        self._cache = _InventoryCache(ttl=30.0)

    def list_blueprints(self):
        if load_blueprints is None:
            return []  # blueprints module not available in this layer
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

    def persistence_status(self) -> dict[str, Any]:
        """Expose the active persistence backend used by the control plane."""

        description = self.state.describe()
        status = {
            "backend": description.get("backend"),
            "path": description.get("path"),
            "exists": description.get("exists"),
            "parent": description.get("parent"),
        }
        for key in (
            "backup_dir",
            "backup_count",
            "backup_retention",
            "journal_path",
            "journal_exists",
            "schema_version",
        ):
            if key in description:
                status[key] = description[key]
        if "dual_write" in description:
            status["dual_write"] = description["dual_write"]
        if hasattr(self.state, "backup_policy"):
            status["policy"] = self.state.backup_policy()
        if hasattr(self.state, "coherence_report"):
            status["coherence"] = self.state.coherence_report()
        return status

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

        # Add critical findings from scoring to notes
        for detail in sec_report.get("details", []):
            if detail.get("severity") == "critical":
                notes.append(
                    f"security-critical:{detail.get('type')}:{detail.get('name', detail.get('domain', ''))}"
                )

        # certs_ok calculation
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

    def dashboard(self, tenant_id: str | None = None) -> DashboardSummary:
        node = self.local_node_summary()

        def _extract_tenant_domain_set() -> set[str]:
            state = self.state.load()
            domains: set[str] = set()
            for rec in state.get("nodes", []):
                if not isinstance(rec, dict):
                    continue
                if rec.get("tenant_id") != tenant_id:
                    continue
                for domain in rec.get("domains", []):
                    if isinstance(domain, str) and domain:
                        domains.add(domain)
            return domains

        def _tenant_filter_items(items: list[Any]) -> list[Any]:
            if not tenant_id:
                return list(items)
            tenant_domains = _extract_tenant_domain_set()
            if not tenant_domains:
                logger.warning(
                    "dashboard tenant filter requested but no tenant domains found",
                    extra={"tenant_id": tenant_id, "node_id": node.node_id},
                )
                return []
            filtered: list[Any] = []
            for item in items:
                if isinstance(item, dict):
                    text = " ".join(
                        str(v).lower()
                        for v in item.values()
                        if isinstance(v, (str, int, float))
                    )
                else:
                    text = str(item).lower()
                if any(domain.lower() in text for domain in tenant_domains):
                    filtered.append(item)
            return filtered

        tenant_scope_warning: str | None = None
        if tenant_id and node.tenant_id and node.tenant_id != tenant_id:
            tenant_scope_warning = (
                f"Local node tenant '{node.tenant_id}' differs from requested tenant '{tenant_id}'. "
                "Returning tenant-scoped dashboard subsets only."
            )

        apps_payload = self._fetch_section("apps")
        services_payload = self._fetch_section("services")
        certs_payload = self._fetch_section("certs")
        backups_payload = self._fetch_section("backups")

        apps = apps_payload.get("apps", []) if isinstance(apps_payload, dict) else []
        services_data = (
            services_payload.get("services", {})
            if isinstance(services_payload, dict)
            else {}
        )
        certs_data = (
            certs_payload.get("certificates", {})
            if isinstance(certs_payload, dict)
            else {}
        )
        backups_data = (
            backups_payload.get("archives", [])
            if isinstance(backups_payload, dict)
            else []
        )

        top_apps = _tenant_filter_items(list(apps))[:10]
        scoped_services = _tenant_filter_items(
            [
                {"name": k, **(v if isinstance(v, dict) else {"status": str(v)})}
                for k, v in services_data.items()
            ]
        )[:15]
        scoped_certs = _tenant_filter_items(
            [
                {"domain": k, **(v if isinstance(v, dict) else {"value": str(v)})}
                for k, v in certs_data.items()
            ]
        )[:15]
        normalized_backups = [
            entry if isinstance(entry, dict) else {"name": str(entry)}
            for entry in list(backups_data)
        ]
        scoped_backups = _tenant_filter_items(normalized_backups)[:10]

        alerts: list[str] = []
        if not scoped_backups:
            alerts.append("No backups found")
        if not scoped_certs:
            alerts.append("No certificate data found")
        if tenant_scope_warning:
            alerts.append(tenant_scope_warning)

        return DashboardSummary(
            node=node,
            top_apps=top_apps,
            alerts=alerts,
            services=scoped_services,
            certs=scoped_certs,
            backups=scoped_backups,
            raw={"tenant_id": tenant_id, "tenant_filter_applied": bool(tenant_id)},
        )

    def import_existing_state(
        self, domain: str | None = None, path: str | None = None
    ) -> dict[str, Any]:
        self.invalidate_cache()
        inv = self.local_inventory()
        report = build_adoption_report(inv, domain, path)
        node_summary = self.local_node_summary().model_dump()
        state = self._ensure_identity_state(
            self.state.load(), enrolled_by="local-bootstrap"
        )
        compatibility = self.compatibility_report()["assessment"]
        node_record = normalize_node_record(
            {
                **node_summary,
                "registered_at": datetime.now(timezone.utc).isoformat(),
                "credential_expires_at": state["identity"].get("expires_at"),
                "compatibility": compatibility,
            }
        )
        runtime_quota = self._validate_runtime_quota_for_node(
            state,
            tenant_id=node_record.get("tenant_id"),
            apps_count=node_record.get("apps_count", 0),
            storage_gb=node_record.get("storage_gb", 0),
        )
        if not runtime_quota.get("allowed", True):
            return {
                "imported": False,
                "idempotent": False,
                "error": runtime_quota.get("error", "runtime_quota_blocked"),
                "quota": runtime_quota,
                "report": report,
                "state_path": str(self.state.path),
            }
        node_record = transition_node_status(
            node_record, "healthy" if compatibility["bootstrap_allowed"] else "degraded"
        )
        state.setdefault("nodes", [])
        state["nodes"] = [
            n for n in state["nodes"] if n.get("node_id") != node_record["node_id"]
        ] + [node_record]
        imports = state.setdefault("imports", [])
        import_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "domain": domain,
            "path": path,
            "report": report,
            "mode": report.get("recommended_mode"),
            "node_id": node_record["node_id"],
        }
        duplicate_import = any(
            isinstance(entry, dict)
            and entry.get("node_id") == import_payload["node_id"]
            and entry.get("domain") == import_payload["domain"]
            and entry.get("path") == import_payload["path"]
            and entry.get("report") == import_payload["report"]
            for entry in imports
        )
        if not duplicate_import:
            imports.append(import_payload)

        snapshots = state.setdefault("inventory_snapshots", [])
        snapshot_payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "kind": "adoption-import",
            "inventory": inv,
            "tenant_id": node_record.get("tenant_id"),
        }
        duplicate_snapshot = any(
            isinstance(entry, dict)
            and entry.get("kind") == "adoption-import"
            and entry.get("inventory") == inv
            for entry in snapshots
        )
        if not duplicate_snapshot:
            snapshots.append(snapshot_payload)
        if node_record["node_id"] not in state["fleet"]["managed_nodes"]:
            state["fleet"]["managed_nodes"].append(node_record["node_id"])
        self.state.save(state)
        return {
            "imported": not duplicate_import,
            "idempotent": duplicate_import,
            "node": node_record,
            "report": report,
            "state_path": str(self.state.path),
        }

    def fleet_summary(self, tenant_id: str | None = None) -> FleetSummary:
        state = self._ensure_identity_state(self.state.load())
        local = self.local_node_summary()

        # In a multi-tenant setup, only include nodes belonging to the tenant.
        # If tenant_id is None, we might return all (admin) or just local (default).
        # For simplicity here, we filter by tenant_id if provided.
        nodes_raw = state.get("nodes", [])
        if tenant_id:
            nodes_raw = [n for n in nodes_raw if n.get("tenant_id") == tenant_id]

        nodes = []
        # Add local node only if it matches tenant_id or no tenant_id filter
        if not tenant_id or local.tenant_id == tenant_id:
            nodes.append(local)

        for node in nodes_raw:
            if node.get("node_id") != local.node_id:
                try:
                    nodes.append(NodeRecord(**node))
                except Exception as exc:
                    logger.warning(
                        "invalid node record ignored in fleet_summary",
                        extra={"node_id": node.get("node_id"), "error": str(exc)},
                    )
        total_apps = sum(n.apps_count for n in nodes)
        total_domains = sum(n.domains_count for n in nodes)
        overall = int(sum(n.health_score for n in nodes) / len(nodes)) if nodes else 0
        return FleetSummary(
            nodes=nodes,
            total_nodes=len(nodes),
            total_apps=total_apps,
            total_domains=total_domains,
            overall_health_score=overall,
        )

    def request_enrollment_token(
        self,
        *,
        requested_by: str,
        mode: str,
        ttl_minutes: int = 30,
        node_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Create and persist a one-time enrollment token for a node."""

        state = self._ensure_identity_state(self.state.load())
        issued = issue_enrollment_token(
            state,
            requested_by=requested_by,
            mode=mode,
            ttl_minutes=ttl_minutes,
            node_id=node_id,
            tenant_id=tenant_id,
        )
        self.state.save(state)
        return issued

    def attest_enrollment(self, **payload: Any) -> dict[str, Any]:
        """Validate an enrollment attestation against compatibility policy."""

        state = self._ensure_identity_state(self.state.load())
        result = attest_node(
            state,
            compatibility_matrix_path=str(
                resolve_compatibility_matrix_path(self.repo_root)
            ),
            **payload,
        )
        self.state.save(state)
        return result

    def register_enrolled_node(
        self,
        *,
        token: str,
        hostname: str,
        node_id: str,
        enrollment_mode: str,
        profile: str | None = None,
        roles: list[str] | None = None,
        apps_count: int = 0,
        storage_gb: int = 0,
    ) -> dict[str, Any]:
        """Finalize registration of a node whose token has been attested."""

        state = self._ensure_identity_state(self.state.load())
        token_record = consume_enrollment_token(state, token, node_id=node_id)

        existing = next(
            (node for node in state.get("nodes", []) if node.get("node_id") == node_id),
            {},
        )
        effective_apps_count = int(apps_count or existing.get("apps_count", 0) or 0)
        effective_storage_gb = int(storage_gb or existing.get("storage_gb", 0) or 0)

        # WS9-T04: Enforce node registration quotas per tenant tier
        tenant_id = token_record.get("tenant_id")
        if tenant_id and is_quota_exceeded is not None:
            # Resolve tenant info (tier)
            tenant_info = next(
                (
                    t
                    for t in state.get("tenants", [])
                    if t.get("tenant_id") == tenant_id
                ),
                {},
            )
            tier = tenant_info.get("tier", TenantTier.FREE)

            # Count existing nodes for this tenant
            tenant_nodes = [
                n for n in state.get("nodes", []) if n.get("tenant_id") == tenant_id
            ]
            if is_quota_exceeded(tier, "max_nodes", len(tenant_nodes)):
                return {
                    "registered": False,
                    "error": f"Quota exceeded for tier '{tier}'. Maximum nodes allowed: {get_quota_limit(tier, 'max_nodes')}",
                }
            runtime_quota = self._validate_runtime_quota_for_node(
                state,
                tenant_id=tenant_id,
                apps_count=effective_apps_count,
                storage_gb=effective_storage_gb,
            )
            if not runtime_quota.get("allowed", True):
                return {
                    "registered": False,
                    "error": runtime_quota.get("error", "runtime_quota_blocked"),
                    "quota": runtime_quota,
                }
        compatibility = self.compatibility_report()["assessment"]
        record = normalize_node_record(
            {
                **existing,
                "node_id": node_id,
                "hostname": hostname,
                "status": "attested",
                "enrollment_mode": enrollment_mode,
                "registered_at": datetime.now(timezone.utc).isoformat(),
                "status_updated_at": datetime.now(timezone.utc).isoformat(),
                "token_id": token_record.get("token_id"),
                "tenant_id": token_record.get("tenant_id"),
                "organization_id": next(
                    (
                        t.get("org_id")
                        for t in state.get("tenants", [])
                        if t.get("tenant_id") == token_record.get("tenant_id")
                    ),
                    None,
                ),
                "credential_expires_at": state.get("identity", {}).get("expires_at"),
                "compatibility": compatibility,
                "profile": profile,
                "roles": roles or existing.get("roles", []),
                "enrolled_by": token_record.get("requested_by"),
                "apps_count": effective_apps_count,
                "storage_gb": effective_storage_gb,
            }
        )
        record = transition_node_status(record, "registered")
        state["nodes"] = [
            node for node in state.get("nodes", []) if node.get("node_id") != node_id
        ] + [record]
        state.setdefault("fleet", {}).setdefault("managed_nodes", [])
        if node_id not in state["fleet"]["managed_nodes"]:
            state["fleet"]["managed_nodes"].append(node_id)
        self.state.save(state)
        return {"registered": True, "node": record}

    def run_lifecycle_action(
        self, *, node_id: str, action: str, operator: str, confirmation: bool = False
    ) -> dict[str, Any]:
        """Finalize registration of a node whose token has been attested."""

        state = self._ensure_identity_state(self.state.load())
        result = apply_lifecycle_action(
            state,
            node_id=node_id,
            action=action,
            operator=operator,
            confirmation=confirmation,
            certs_dir=str(self.state.path.parent / "certs"),
        )
        self.state.save(state)
        return result

    def fleet_lifecycle(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Return the current fleet state, optionally filtered by tenant."""

        state = self.state.load()
        nodes = state.get("nodes", [])
        if tenant_id:
            nodes = [n for n in nodes if n.get("tenant_id") == tenant_id]

        from nexora_core.node_lifecycle import summarize_fleet_lifecycle

        return summarize_fleet_lifecycle(nodes)

    def _validate_runtime_quota_for_node(
        self,
        state: dict[str, Any],
        *,
        tenant_id: str | None,
        apps_count: int,
        storage_gb: int,
    ) -> dict[str, Any]:
        """P9-T05 runtime quota guard for node-level app/storage metrics."""

        if not tenant_id or is_quota_exceeded is None:
            return {"allowed": True, "reason": "no-tenant-scope"}
        tenant_info = next(
            (
                tenant
                for tenant in state.get("tenants", [])
                if isinstance(tenant, dict) and tenant.get("tenant_id") == tenant_id
            ),
            {},
        )
        tier = tenant_info.get("tier", TenantTier.FREE)
        apps_limit = get_quota_limit(tier, "max_apps_per_node")
        storage_limit = get_quota_limit(tier, "max_storage_gb")
        apps_count = max(0, int(apps_count or 0))
        storage_gb = max(0, int(storage_gb or 0))

        if is_quota_exceeded(tier, "max_apps_per_node", apps_count):
            return {
                "allowed": False,
                "resource": "max_apps_per_node",
                "current": apps_count,
                "limit": apps_limit,
                "error": f"Quota exceeded for tenant '{tenant_id}': apps per node {apps_count}/{apps_limit}",
            }
        if is_quota_exceeded(tier, "max_storage_gb", storage_gb):
            return {
                "allowed": False,
                "resource": "max_storage_gb",
                "current": storage_gb,
                "limit": storage_limit,
                "error": f"Quota exceeded for tenant '{tenant_id}': storage {storage_gb}GB/{storage_limit}GB",
            }
        return {
            "allowed": True,
            "tier": str(tier),
            "max_apps_per_node": apps_limit,
            "max_storage_gb": storage_limit,
            "apps_count": apps_count,
            "storage_gb": storage_gb,
        }

    def tenant_usage_vs_quota(self, tenant_id: str | None = None) -> dict[str, Any]:
        """WS9-T06: expose canonical tenant usage versus quota limits."""

        if is_quota_exceeded is None:
            return {"error": "Quota module not available in this layer"}

        state = self.state.load()
        tenants = [
            tenant
            for tenant in state.get("tenants", [])
            if isinstance(tenant, dict) and tenant.get("tenant_id")
        ]

        if tenant_id:
            tenants = [
                tenant for tenant in tenants if tenant.get("tenant_id") == tenant_id
            ]
            if not tenants:
                return {
                    "tenant_id": tenant_id,
                    "error": f"Unknown tenant_id: {tenant_id}",
                    "usage": {},
                    "limits": {},
                    "exceeded": {},
                }

        def _coerce_int(value: Any) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        reports: list[dict[str, Any]] = []
        nodes = [node for node in state.get("nodes", []) if isinstance(node, dict)]
        for tenant in tenants:
            current_tenant_id = str(tenant.get("tenant_id"))
            tier = str(tenant.get("tier") or TenantTier.FREE)
            tenant_nodes = [
                node for node in nodes if node.get("tenant_id") == current_tenant_id
            ]

            nodes_count = len(tenant_nodes)
            apps_per_node = [
                _coerce_int(node.get("apps_count")) for node in tenant_nodes
            ]
            apps_total = sum(apps_per_node)
            max_apps_on_single_node = max(apps_per_node) if apps_per_node else 0
            storage_used_gb = sum(
                _coerce_int(node.get("storage_gb")) for node in tenant_nodes
            )

            limits = {
                "max_nodes": get_quota_limit(tier, "max_nodes"),
                "max_apps_per_node": get_quota_limit(tier, "max_apps_per_node"),
                "max_storage_gb": get_quota_limit(tier, "max_storage_gb"),
            }
            usage = {
                "nodes_count": nodes_count,
                "apps_total": apps_total,
                "max_apps_on_single_node": max_apps_on_single_node,
                "storage_used_gb": storage_used_gb,
            }
            exceeded = {
                "max_nodes": is_quota_exceeded(tier, "max_nodes", nodes_count),
                "max_apps_per_node": is_quota_exceeded(
                    tier, "max_apps_per_node", max_apps_on_single_node
                ),
                "max_storage_gb": is_quota_exceeded(
                    tier, "max_storage_gb", storage_used_gb
                ),
            }

            reports.append(
                {
                    "tenant_id": current_tenant_id,
                    "organization_id": tenant.get("org_id"),
                    "tier": tier,
                    "entitlements": get_tenant_entitlements(tier),
                    "usage": usage,
                    "limits": limits,
                    "exceeded": exceeded,
                    "within_quota": not any(exceeded.values()),
                }
            )

        if tenant_id:
            return reports[0]
        return {"tenants": reports, "total_tenants": len(reports)}

    def adoption_report(
        self, domain: str | None = None, path: str | None = None
    ) -> dict[str, Any]:
        return build_adoption_report(self.local_inventory(), domain, path)

    def identity(self) -> dict[str, Any]:
        """Finalize registration of a node whose token has been attested."""

        state = self._ensure_identity_state(self.state.load())
        self.state.save(state)
        return state["identity"]

    def branding_profile(self, slug: str | None = None) -> dict[str, Any]:
        """Return the current branding profile."""
        state = self.state.load()
        return state.get("branding", {})

    def purge_tenant_data(self, tenant_id: str) -> dict[str, Any]:
        """WS9-T06: Securely purge all data related to a tenant (GDPR/Offboarding)."""
        state = self.state.load()

        # 1. Collect nodes to remove
        tenant_nodes = [
            n for n in state.get("nodes", []) if n.get("tenant_id") == tenant_id
        ]
        node_ids = [n.get("node_id") for n in tenant_nodes]

        # 2. Purge secrets
        from nexora_core.auth import SecretStore

        store = SecretStore(self.state.path.parent / "secrets")
        store.purge_tenant_secrets(tenant_id)

        # 3. Filter state entities
        state["nodes"] = [
            n for n in state.get("nodes", []) if n.get("tenant_id") != tenant_id
        ]
        state["tenants"] = [
            t for t in state.get("tenants", []) if t.get("tenant_id") != tenant_id
        ]

        # Filter audit logs and enrollment events
        if "security_audit" in state:
            state["security_audit"] = [
                e for e in state["security_audit"] if e.get("tenant_id") != tenant_id
            ]

        if "enrollment_events" in state:
            state["enrollment_events"] = [
                e for e in state["enrollment_events"] if e.get("tenant_id") != tenant_id
            ]

        # 4. Remove from fleet listing
        if "fleet" in state and "managed_nodes" in state["fleet"]:
            state["fleet"]["managed_nodes"] = [
                nid for nid in state["fleet"]["managed_nodes"] if nid not in node_ids
            ]

        self.state.save(state)
        self.invalidate_cache()

        return {
            "success": True,
            "tenant_id": tenant_id,
            "purged_nodes_count": len(node_ids),
            "message": f"Tenant {tenant_id} and all associated data have been purged successfully.",
        }

    def onboard_tenant(
        self, tenant_id: str, organization_id: str, tier: str = "free"
    ) -> dict[str, Any]:
        """WS9-T07: Formalize tenant onboarding and environment separation."""
        state = self.state.load()
        state.setdefault("tenants", [])

        if any(t.get("tenant_id") == tenant_id for t in state["tenants"]):
            return {"success": False, "error": f"Tenant {tenant_id} already exists"}

        new_tenant = {
            "tenant_id": tenant_id,
            "org_id": organization_id,
            "tier": tier,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        }
        state["tenants"].append(new_tenant)
        self.state.save(state)

        return {"success": True, "tenant": new_tenant}

    def list_tenants(self, organization_id: str | None = None) -> list[dict[str, Any]]:
        state = self.state.load()
        tenants = state.get("tenants", [])
        if organization_id:
            tenants = [t for t in tenants if t.get("org_id") == organization_id]
        return tenants
        state = self.state.load()
        return state.get(
            "branding",
            {
                "brand_name": NEXORA_IDENTITY["brand_name"],
                "accent": NEXORA_IDENTITY["accent"],
                "portal_title": NEXORA_IDENTITY["console_title"],
                "tagline": NEXORA_IDENTITY["tagline"],
                "sections": ["apps", "security", "monitoring", "pra", "fleet"],
            },
        )
