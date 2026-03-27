"""Per-node / per-service / per-operator secret isolation.

WS4-T04: Secrets are stored in isolated directory namespaces with strict
file permissions.  Each secret is scoped to exactly one (owner_type, owner_id)
pair and can only be read by the owning process.

Directory layout::

    <state_dir>/secrets/
        node/<node_id>/api-token
        service/<service_name>/api-token
        operator/<operator_id>/api-token
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_OWNER_TYPES = {"node", "service", "operator"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _secret_path(state_dir: str | Path, owner_type: str, owner_id: str) -> Path:
    if owner_type not in VALID_OWNER_TYPES:
        raise ValueError(f"Invalid owner type: {owner_type}")
    # Sanitize owner_id to prevent path traversal.
    safe_id = owner_id.replace("/", "_").replace("..", "_").replace("\\", "_")
    return Path(state_dir) / "secrets" / owner_type / safe_id / "api-token"


def issue_secret(
    state_dir: str | Path,
    *,
    owner_type: str,
    owner_id: str,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Generate and persist a scoped secret for the given owner.

    Returns metadata (never the raw token in logs).
    """
    path = _secret_path(state_dir, owner_type, owner_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    token = secrets.token_urlsafe(32)
    meta = {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "scopes": scopes or [],
        "issued_at": _utc_now_iso(),
        "revoked_at": None,
    }
    # Write token file (restricted permissions).
    path.write_text(token)
    path.chmod(0o600)

    # Write metadata alongside the token.
    meta_path = path.parent / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    meta_path.chmod(0o600)

    return {
        "owner_type": owner_type,
        "owner_id": owner_id,
        "token_path": str(path),
        "scopes": meta["scopes"],
        "issued_at": meta["issued_at"],
    }


def read_secret(state_dir: str | Path, *, owner_type: str, owner_id: str) -> str | None:
    """Read the raw secret for an owner.  Returns None if absent or revoked."""
    path = _secret_path(state_dir, owner_type, owner_id)
    if not path.exists():
        return None

    meta_path = path.parent / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("revoked_at"):
            return None

    return path.read_text().strip()


def revoke_secret(
    state_dir: str | Path, *, owner_type: str, owner_id: str
) -> dict[str, Any]:
    """Revoke a secret by marking its metadata and wiping the token file."""
    path = _secret_path(state_dir, owner_type, owner_id)
    meta_path = path.parent / "meta.json"

    now = _utc_now_iso()

    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["revoked_at"] = now
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        meta_path.chmod(0o600)

    # Overwrite the token file with empty content.
    if path.exists():
        path.write_text("")
        path.chmod(0o600)

    return {"owner_type": owner_type, "owner_id": owner_id, "revoked_at": now}


def list_secrets(
    state_dir: str | Path, *, owner_type: str | None = None
) -> list[dict[str, Any]]:
    """List secret metadata (never raw tokens) for auditing."""
    base = Path(state_dir) / "secrets"
    if not base.exists():
        return []

    results: list[dict[str, Any]] = []
    types_to_scan = [owner_type] if owner_type else list(VALID_OWNER_TYPES)

    for otype in types_to_scan:
        type_dir = base / otype
        if not type_dir.is_dir():
            continue
        for owner_dir in sorted(type_dir.iterdir()):
            meta_path = owner_dir / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                results.append(meta)
            else:
                results.append(
                    {
                        "owner_type": otype,
                        "owner_id": owner_dir.name,
                        "scopes": [],
                        "issued_at": None,
                        "revoked_at": None,
                    }
                )
    return results


def verify_secret(
    state_dir: str | Path,
    *,
    owner_type: str,
    owner_id: str,
    provided_token: str,
) -> bool:
    """Constant-time comparison of a provided token against the stored one."""
    stored = read_secret(state_dir, owner_type=owner_type, owner_id=owner_id)
    if stored is None:
        return False
    return secrets.compare_digest(stored, provided_token)
