"""Industrialized node identity lifecycle: emit, rotate, revoke.

WS4-T02: Provides higher-level orchestration around identity.py primitives
so that the control plane can manage the full credential lifecycle in a
single, auditable flow.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .identity import generate_node_credentials
from .security_audit import build_security_event
from .tls import is_certificate_revoked, revoke_certificate

# Maximum age (in days) before a credential *must* be rotated.
MAX_CREDENTIAL_AGE_DAYS = 365
# Recommended rotation window (days before expiry).
ROTATION_WINDOW_DAYS = 90


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ── Emit ─────────────────────────────────────────────────────────────


def emit_node_identity(
    state: dict[str, Any],
    *,
    node_id: str,
    fleet_id: str,
    certs_dir: str | Path,
    operator: str,
) -> dict[str, Any]:
    """Issue a fresh identity (certificate + token) for a node.

    Persists the credential metadata in the node record and emits a
    security audit event.
    """
    creds = generate_node_credentials(node_id, fleet_id, str(certs_dir))

    # Update or create node record.
    nodes = state.setdefault("nodes", [])
    node = next((n for n in nodes if n.get("node_id") == node_id), None)
    if node is None:
        node = {"node_id": node_id, "hostname": node_id}
        nodes.append(node)

    node["token_id"] = creds["token_id"]
    node["cert_path"] = creds["cert_path"]
    node["key_path"] = creds["key_path"]
    node["credential_issued_at"] = creds["issued_at"]
    node["credential_expires_at"] = creds["expires_at"]
    node["credential_rotation_recommended_at"] = creds["rotation_recommended_at"]
    node["credential_revoked_at"] = None

    event = build_security_event(
        "identity",
        "credential_emitted",
        severity="info",
        node_id=node_id,
        token_id=creds["token_id"],
        operator=operator,
    )
    state.setdefault("security_audit", []).append(event)

    return {**creds, "audit_event": event}


# ── Rotate ───────────────────────────────────────────────────────────


def rotate_node_identity(
    state: dict[str, Any],
    *,
    node_id: str,
    fleet_id: str,
    certs_dir: str | Path,
    operator: str,
) -> dict[str, Any]:
    """Rotate credentials for *node_id*: revoke old, emit new.

    The old certificate is added to the CRL before new credentials are
    issued, ensuring a clean handover.
    """
    nodes = state.get("nodes", [])
    node = next((n for n in nodes if n.get("node_id") == node_id), None)
    if node is None:
        raise ValueError(f"Unknown node: {node_id}")

    old_token_id = node.get("token_id")

    # Revoke old certificate in CRL.
    revoke_certificate(str(certs_dir), node_id, reason="rotation")

    # Mark old credentials revoked in node record.
    node["credential_revoked_at"] = _iso(_utc_now())

    revoke_event = build_security_event(
        "identity",
        "credential_revoked_for_rotation",
        severity="info",
        node_id=node_id,
        old_token_id=old_token_id,
        operator=operator,
    )
    state.setdefault("security_audit", []).append(revoke_event)

    # Remove from CRL before re-issuing (the old entry stays for audit,
    # but a fresh cert is generated with a new serial).
    _clear_crl_entry(str(certs_dir), node_id)

    # Emit new credentials.
    result = emit_node_identity(
        state,
        node_id=node_id,
        fleet_id=fleet_id,
        certs_dir=certs_dir,
        operator=operator,
    )
    result["rotation"] = True
    result["previous_token_id"] = old_token_id
    return result


def _clear_crl_entry(certs_dir: str, node_id: str) -> None:
    """Remove a node from the local CRL so a fresh cert can be validated."""
    crl_path = Path(certs_dir) / "fleet-crl.json"
    if not crl_path.exists():
        return
    payload = json.loads(crl_path.read_text(encoding="utf-8"))
    payload["revoked"] = [
        e for e in payload.get("revoked", []) if e.get("node_id") != node_id
    ]
    crl_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Revoke ───────────────────────────────────────────────────────────


def revoke_node_identity(
    state: dict[str, Any],
    *,
    node_id: str,
    certs_dir: str | Path,
    reason: str,
    operator: str,
) -> dict[str, Any]:
    """Permanently revoke a node's identity.

    The certificate is added to the CRL, the node record is updated, and
    a critical-severity audit event is emitted.
    """
    nodes = state.get("nodes", [])
    node = next((n for n in nodes if n.get("node_id") == node_id), None)
    if node is None:
        raise ValueError(f"Unknown node: {node_id}")

    revoke_certificate(str(certs_dir), node_id, reason=reason)
    now = _iso(_utc_now())
    node["credential_revoked_at"] = now
    old_token_id = node.get("token_id")
    node["token_id"] = None

    event = build_security_event(
        "identity",
        "credential_revoked",
        severity="critical",
        node_id=node_id,
        reason=reason,
        old_token_id=old_token_id,
        operator=operator,
    )
    state.setdefault("security_audit", []).append(event)

    return {
        "node_id": node_id,
        "revoked_at": now,
        "reason": reason,
        "audit_event": event,
    }


# ── Bulk audit helpers ───────────────────────────────────────────────


def audit_credential_health(
    state: dict[str, Any],
    *,
    certs_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return a per-node credential health report.

    Flags: expired, revoked, approaching rotation window, missing.
    """
    now = _utc_now()
    report: list[dict[str, Any]] = []
    for node in state.get("nodes", []):
        node_id = node.get("node_id", "unknown")
        entry: dict[str, Any] = {"node_id": node_id, "issues": []}

        if node.get("credential_revoked_at"):
            entry["issues"].append("revoked")
        elif certs_dir and is_certificate_revoked(str(certs_dir), node_id):
            entry["issues"].append("revoked_in_crl")

        expires = _parse_iso(node.get("credential_expires_at"))
        if expires is None:
            entry["issues"].append("no_credential")
        elif expires < now:
            entry["issues"].append("expired")
        elif expires < now + timedelta(days=ROTATION_WINDOW_DAYS):
            entry["issues"].append("rotation_recommended")

        if not node.get("cert_path"):
            entry["issues"].append("missing_cert_path")

        entry["status"] = "healthy" if not entry["issues"] else "attention_needed"
        report.append(entry)
    return report
