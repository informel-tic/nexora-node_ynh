"""Tenant scope, actor role resolution, and scope/permission validators.

Part of the nexora_node_sdk.auth package.  All symbols here are re-exported
from nexora_node_sdk.auth.__init__ for backward compatibility.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from pathlib import Path

from ._token import _token_scope_path_candidates, _token_role_path_candidates

logger = logging.getLogger(__name__)

# ── Tenant scope loading ──────────────────────────────────────────────


def _load_token_tenant_scopes() -> dict[str, set[str]]:
    """Load optional API token -> allowed tenant ids mapping.

    Supported formats:
    - {"token-value": ["tenant-a", "tenant-b"]}
    - {"tokens": [{"token": "token-value", "tenants": ["tenant-a"]}]}
    """

    for path_str in _token_scope_path_candidates():
        if not path_str:
            continue
        path = Path(path_str)
        if not path.exists():
            continue

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        mapping: dict[str, set[str]] = {}
        if isinstance(raw, dict) and isinstance(raw.get("tokens"), list):
            for record in raw["tokens"]:
                if not isinstance(record, dict):
                    continue
                token = str(record.get("token", "")).strip()
                tenants = record.get("tenants", [])
                if not token or not isinstance(tenants, list):
                    continue
                normalized = {
                    str(item).strip() for item in tenants if str(item).strip()
                }
                if normalized:
                    mapping[token] = normalized
            return mapping

        if isinstance(raw, dict):
            for token, tenants in raw.items():
                if not isinstance(token, str) or not token.strip():
                    continue
                if not isinstance(tenants, list):
                    continue
                normalized = {
                    str(item).strip() for item in tenants if str(item).strip()
                }
                if normalized:
                    mapping[token.strip()] = normalized
            return mapping

    return {}


def _enforce_token_tenant_scope(token: str, tenant_id: str | None) -> bool:
    """Return whether token can access the requested tenant scope."""

    mapping = _load_token_tenant_scopes()
    if not mapping:
        return True
    allowed = mapping.get(token)
    if not allowed:
        return False
    if not tenant_id:
        return False
    return tenant_id in allowed


# ── Actor role loading ────────────────────────────────────────────────


def _load_token_actor_roles() -> dict[str, str]:
    """Load optional API token -> actor role mapping.

    Supported formats:
    - {"token-value": "operator"}
    - {"tokens": [{"token": "token-value", "actor_role": "operator"}]}
    """

    for path_str in _token_role_path_candidates():
        if not path_str:
            continue
        path = Path(path_str)
        if not path.exists():
            continue

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        mapping: dict[str, str] = {}
        if isinstance(raw, dict) and isinstance(raw.get("tokens"), list):
            for record in raw["tokens"]:
                if not isinstance(record, dict):
                    continue
                token_val = str(record.get("token", "")).strip()
                role = str(record.get("actor_role", "")).strip()
                if not token_val or not role:
                    continue
                try:
                    mapping[token_val] = validate_operator_surface_role(role)
                except ValueError:
                    continue
            return mapping

        if isinstance(raw, dict):
            for token_val, role in raw.items():
                if not isinstance(token_val, str) or not token_val.strip():
                    continue
                if not isinstance(role, str) or not role.strip():
                    continue
                try:
                    mapping[token_val.strip()] = validate_operator_surface_role(role)
                except ValueError:
                    continue
            return mapping

    return {}


def resolve_actor_role_for_token(token: str) -> str | None:
    """Resolve trusted actor role bound to a token, if configured."""

    mapping = _load_token_actor_roles()
    return mapping.get(token)


# ── HMAC tenant-scope claim ───────────────────────────────────────────


def build_tenant_scope_claim(token: str, tenant_id: str) -> str:
    """Build an HMAC claim binding a tenant scope request to a token."""

    normalized_tenant = tenant_id.strip()
    return hmac.new(
        key=token.encode("utf-8"),
        msg=normalized_tenant.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


# ── Scope / role constants and validators ─────────────────────────────

NODE_TOKEN_SCOPES = {
    "read_inventory",
    "sync_branding",
    "execute_remote_action",
    "rotate_credentials",
}


def validate_actor_role(value: str) -> str:
    """Validate an actor role used in auth and audit flows."""

    allowed = {"human", "machine", "console", "mcp"}
    normalized = value.strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Unsupported actor role: {value}")
    return normalized


def validate_operator_surface_role(value: str) -> str:
    """Validate trusted role bindings for operator-only routes."""

    allowed = {"operator", "admin", "architect"}
    normalized = value.strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Unsupported operator surface role: {value}")
    return normalized


def validate_scope(scope: str) -> str:
    """Validate a token scope name."""

    normalized = scope.strip()
    if normalized not in NODE_TOKEN_SCOPES:
        raise ValueError(f"Unsupported auth scope: {scope}")
    return normalized


def issue_node_secret(
    node_id: str,
    *,
    scopes: list[str],
    state_dir: str | Path = "/opt/nexora/var",
) -> dict[str, str | list[str]]:
    """Issue a scoped per-node secret and persist it on disk."""

    for scope in scopes:
        validate_scope(scope)
    token = secrets.token_urlsafe(32)
    token_id = f"node-secret-{hashlib.sha256(node_id.encode()).hexdigest()[:10]}"
    path = Path(state_dir) / "node-secrets" / f"{node_id}.token"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    path.chmod(0o600)
    return {
        "node_id": node_id,
        "token_id": token_id,
        "token_path": str(path),
        "scopes": scopes,
    }
