"""WS4-T04: Scoped secret isolation per node, service, and operator.

Part of the nexora_core.auth package.  All symbols here are re-exported
from nexora_core.auth.__init__ for backward compatibility.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────

# Scope kinds for scoped secret isolation
VALID_SCOPES = {"node", "service", "operator"}

# Permissions that can be granted per scope
SCOPE_PERMISSIONS: dict[str, set[str]] = {
    "node": {
        "read_inventory",
        "sync_branding",
        "execute_remote_action",
        "rotate_credentials",
        "heartbeat",
    },
    "service": {
        "read_inventory",
        "sync_config",
        "create_backup",
        "restart_service",
        "read_metrics",
    },
    "operator": {
        "read_inventory",
        "sync_branding",
        "execute_remote_action",
        "rotate_credentials",
        "install_app",
        "remove_app",
        "upgrade_app",
        "restore_backup",
        "system_upgrade",
        "create_backup",
        "restart_service",
        "sync_config",
        "read_metrics",
        "heartbeat",
        "deploy_blueprint",
        "execute_failover",
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── SecretStore ───────────────────────────────────────────────────────


class SecretStore:
    """Manages scoped secrets for nodes, services, and operators.

    Secrets are persisted on disk under ``{state_dir}/secrets/`` with 0o600
    permissions.  Each secret is bound to a scope (node, service, operator),
    an entity ID, and a set of permissions.

    The store supports issuance, validation, and revocation of scoped secrets
    with constant-time token comparison and replay detection via consumed tokens.
    """

    def __init__(self, state_dir: str | Path = "/opt/nexora/var"):
        self._state_dir = Path(state_dir)
        self._secrets_dir = self._state_dir / "secrets"
        self._secrets_dir.mkdir(parents=True, exist_ok=True)
        self._consumed_tokens_path = self._state_dir / "consumed-token-digests.json"
        self._consumed_tokens_seen_at: dict[str, float] = {}
        self._consumed_tokens: set[str] = set()
        self._load_consumed_tokens()

    def _replay_retention_seconds(self) -> int:
        raw = os.environ.get("NEXORA_REPLAY_RETENTION_SECONDS", "86400").strip()
        try:
            return max(300, int(raw))
        except ValueError:
            return 86400

    def _load_consumed_tokens(self) -> None:
        if not self._consumed_tokens_path.exists():
            self._consumed_tokens.clear()
            self._consumed_tokens_seen_at.clear()
            return

        try:
            payload = json.loads(self._consumed_tokens_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "unable to read consumed token registry",
                extra={"path": str(self._consumed_tokens_path)},
            )
            self._consumed_tokens.clear()
            self._consumed_tokens_seen_at.clear()
            return

        rows = payload.get("tokens", []) if isinstance(payload, dict) else []
        now = time.time()
        retention = self._replay_retention_seconds()
        seen: dict[str, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            digest = str(row.get("digest", "")).strip()
            if not digest:
                continue
            try:
                consumed_at = float(row.get("consumed_at", 0))
            except (TypeError, ValueError):
                continue
            if now - consumed_at > retention:
                continue
            seen[digest] = consumed_at

        self._consumed_tokens_seen_at = seen
        self._consumed_tokens = set(seen.keys())

    def _persist_consumed_tokens(self) -> None:
        now = time.time()
        retention = self._replay_retention_seconds()
        self._consumed_tokens_seen_at = {
            digest: ts
            for digest, ts in self._consumed_tokens_seen_at.items()
            if now - ts <= retention
        }
        self._consumed_tokens = set(self._consumed_tokens_seen_at.keys())

        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "tokens": [
                {"digest": digest, "consumed_at": ts}
                for digest, ts in sorted(
                    self._consumed_tokens_seen_at.items(), key=lambda item: item[1]
                )
            ],
        }
        try:
            self._consumed_tokens_path.parent.mkdir(parents=True, exist_ok=True)
            self._consumed_tokens_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self._consumed_tokens_path.chmod(0o600)
        except OSError:
            logger.warning(
                "unable to persist consumed token registry",
                extra={"path": str(self._consumed_tokens_path)},
            )

    @property
    def secrets_dir(self) -> Path:
        return self._secrets_dir

    def _scope_dir(self, tenant_id: str, scope: str) -> Path:
        if scope not in VALID_SCOPES:
            raise ValueError(f"Invalid scope: {scope}. Must be one of {VALID_SCOPES}")
        d = self._secrets_dir / tenant_id / scope
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _record_path(self, tenant_id: str, scope: str, entity_id: str) -> Path:
        safe_id = hashlib.sha256(entity_id.encode("utf-8")).hexdigest()[:24]
        return self._scope_dir(tenant_id, scope) / f"{safe_id}.json"

    def issue_scoped_secret(
        self,
        scope: str,
        entity_id: str,
        permissions: list[str],
        *,
        tenant_id: str = "default-tenant",
        ttl_seconds: int = 86400,
    ) -> dict[str, Any]:
        """Issue a scoped secret for an entity within a tenant.

        Args:
            scope: One of 'node', 'service', 'operator'.
            entity_id: The entity identifier (node_id, service name, operator name).
            permissions: List of permission strings granted to this secret.
            tenant_id: The ID of the tenant owning this secret.
            ttl_seconds: Time-to-live in seconds (default 24h).

        Returns:
            Dict with token, token_id, scope, entity_id, tenant_id, permissions, and expiry.
        """

        if scope not in VALID_SCOPES:
            raise ValueError(f"Invalid scope: {scope}")

        allowed = SCOPE_PERMISSIONS.get(scope, set())
        invalid = set(permissions) - allowed
        if invalid:
            raise ValueError(f"Permissions {invalid} not allowed for scope '{scope}'")

        token = secrets.token_urlsafe(32)
        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        token_id = f"secret-{scope}-{hashlib.sha256(entity_id.encode()).hexdigest()[:8]}-{secrets.token_hex(4)}"
        now = datetime.now(timezone.utc)
        expires_at = now.timestamp() + ttl_seconds

        record = {
            "token_id": token_id,
            "token_digest": token_digest,
            "scope": scope,
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "permissions": permissions,
            "issued_at": now.isoformat(),
            "expires_at_ts": expires_at,
            "expires_at": datetime.fromtimestamp(
                expires_at, tz=timezone.utc
            ).isoformat(),
            "revoked": False,
            "revoked_at": None,
        }

        # Load existing records for this entity (may have multiple tokens)
        rpath = self._record_path(tenant_id, scope, entity_id)
        records: list[dict[str, Any]] = []
        if rpath.exists():
            try:
                data = json.loads(rpath.read_text(encoding="utf-8"))
                records = data if isinstance(data, list) else [data]
            except (json.JSONDecodeError, OSError):
                records = []
        records.append(record)

        rpath.write_text(
            json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        try:
            rpath.chmod(0o600)
        except OSError:
            pass

        return {
            "token": token,
            "token_id": token_id,
            "scope": scope,
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "permissions": permissions,
            "expires_at": record["expires_at"],
        }

    def validate_scoped_secret(
        self,
        token: str,
        required_scope: str,
        *,
        required_tenant_id: str | None = None,
        required_permission: str | None = None,
    ) -> dict[str, Any]:
        """Validate a scoped secret token.

        Checks:
        1. Token digest matches a stored record.
        2. Token scope matches the required scope.
        3. Token tenant ID matches the required tenant ID (if provided).
        4. Token is not expired.
        5. Token is not revoked.
        6. Token has not been consumed (replay detection).
        7. Required permission is in the token's permission set.

        Returns:
            Dict with valid=True/False, entity_id, tenant_id, scope, permissions, and reasons.
        """

        if required_scope not in VALID_SCOPES:
            return {
                "valid": False,
                "reasons": [f"invalid required scope: {required_scope}"],
            }

        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self._load_consumed_tokens()

        # Check replay
        if token_digest in self._consumed_tokens:
            return {
                "valid": False,
                "reasons": ["token has already been consumed (replay detected)"],
            }

        # Search through all records in this scope across all tenants if tenant_id not specified,
        # or restricted to the specific tenant path if specified.
        if required_tenant_id:
            search_dirs = [self._secrets_dir / required_tenant_id / required_scope]
        else:
            search_dirs = list(self._secrets_dir.glob(f"*/{required_scope}"))

        now = time.time()
        for scope_dir in search_dirs:
            if not scope_dir.exists():
                continue

            for record_file in scope_dir.glob("*.json"):
                try:
                    data = json.loads(record_file.read_text(encoding="utf-8"))
                    records = data if isinstance(data, list) else [data]
                except (json.JSONDecodeError, OSError):
                    continue

                for record in records:
                    if not secrets.compare_digest(
                        record.get("token_digest", ""), token_digest
                    ):
                        continue

                    # Found matching token — all validation logic is inside the loop
                    reasons: list[str] = []

                    if record.get("revoked"):
                        reasons.append("token has been revoked")
                        return {
                            "valid": False,
                            "entity_id": record["entity_id"],
                            "reasons": reasons,
                        }

                    if record.get("scope") != required_scope:
                        reasons.append(
                            f"token scope '{record['scope']}' does not match required '{required_scope}'"
                        )
                        return {
                            "valid": False,
                            "entity_id": record["entity_id"],
                            "tenant_id": record.get("tenant_id"),
                            "reasons": reasons,
                        }

                    if (
                        required_tenant_id
                        and record.get("tenant_id") != required_tenant_id
                    ):
                        reasons.append(
                            f"token tenant '{record.get('tenant_id')}' does not match required '{required_tenant_id}'"
                        )
                        return {
                            "valid": False,
                            "entity_id": record["entity_id"],
                            "tenant_id": record.get("tenant_id"),
                            "reasons": reasons,
                        }

                    if now > record.get("expires_at_ts", 0):
                        reasons.append("token has expired")
                        return {
                            "valid": False,
                            "entity_id": record["entity_id"],
                            "tenant_id": record.get("tenant_id"),
                            "reasons": reasons,
                        }

                    if required_permission and required_permission not in record.get(
                        "permissions", []
                    ):
                        reasons.append(
                            f"token lacks required permission: {required_permission}"
                        )
                        return {
                            "valid": False,
                            "entity_id": record["entity_id"],
                            "tenant_id": record.get("tenant_id"),
                            "permissions": record.get("permissions", []),
                            "reasons": reasons,
                        }

                    reasons.append("token validated successfully")
                    return {
                        "valid": True,
                        "token_id": record["token_id"],
                        "entity_id": record["entity_id"],
                        "tenant_id": record.get("tenant_id"),
                        "scope": record["scope"],
                        "permissions": record.get("permissions", []),
                        "reasons": reasons,
                    }

        return {"valid": False, "reasons": ["token not found in any record"]}

    def consume_token(self, token: str) -> None:
        """Mark a token as consumed to prevent replay."""

        token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self._consumed_tokens.add(token_digest)
        self._consumed_tokens_seen_at[token_digest] = time.time()
        self._persist_consumed_tokens()

    def revoke_scoped_secret(
        self,
        entity_id: str,
        scope: str,
        *,
        tenant_id: str = "default-tenant",
    ) -> dict[str, Any]:
        """Revoke all secrets for an entity within a scope and tenant.

        Returns:
            Dict with revoked_count, tenant_id, and entity_id.
        """

        if scope not in VALID_SCOPES:
            raise ValueError(f"Invalid scope: {scope}")

        rpath = self._record_path(tenant_id, scope, entity_id)
        revoked_count = 0

        if rpath.exists():
            try:
                data = json.loads(rpath.read_text(encoding="utf-8"))
                records = data if isinstance(data, list) else [data]
                for record in records:
                    if not record.get("revoked"):
                        record["revoked"] = True
                        record["revoked_at"] = _utc_now_iso()
                        revoked_count += 1
                rpath.write_text(
                    json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            except (json.JSONDecodeError, OSError):
                pass

        return {
            "entity_id": entity_id,
            "tenant_id": tenant_id,
            "scope": scope,
            "revoked_count": revoked_count,
        }

    def purge_tenant_secrets(self, tenant_id: str) -> bool:
        """WS9-T06: Securely delete all secrets belonging to a tenant."""
        tenant_dir = self._secrets_dir / tenant_id
        if tenant_dir.exists() and tenant_dir.is_dir():
            import shutil

            try:
                shutil.rmtree(tenant_dir)
                return True
            except OSError as exc:
                logger.error(
                    "Failed to purge tenant secrets for %s: %s", tenant_id, exc
                )
                return False
        return False

    def list_secrets(
        self,
        scope: str | None = None,
        *,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List secret metadata (without token values) for a scope/tenant or all."""

        scopes = [scope] if scope else list(VALID_SCOPES)
        tenants = (
            [tenant_id]
            if tenant_id
            else [p.name for p in self._secrets_dir.iterdir() if p.is_dir()]
        )

        results: list[dict[str, Any]] = []
        for t in tenants:
            for s in scopes:
                scope_dir = self._secrets_dir / t / s
                if not scope_dir.exists():
                    continue
                for record_file in scope_dir.glob("*.json"):
                    try:
                        data = json.loads(record_file.read_text(encoding="utf-8"))
                        records = data if isinstance(data, list) else [data]
                        for record in records:
                            results.append(
                                {
                                    "token_id": record.get("token_id"),
                                    "scope": record.get("scope"),
                                    "tenant_id": record.get("tenant_id"),
                                    "entity_id": record.get("entity_id"),
                                    "permissions": record.get("permissions", []),
                                    "issued_at": record.get("issued_at"),
                                    "expires_at": record.get("expires_at"),
                                    "revoked": record.get("revoked", False),
                                }
                            )
                    except (json.JSONDecodeError, OSError):
                        continue
        return results
