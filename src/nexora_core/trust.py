"""Trust model formalization for Nexora fleet nodes.

Defines trust levels, evaluation logic, and operation-to-trust mapping
used by the control plane to gate actions based on node posture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any


class TrustLevel(IntEnum):
    """Ordered trust levels for fleet nodes."""

    UNTRUSTED = 0
    ENROLLED = 1
    ATTESTED = 2
    VERIFIED = 3
    TRUSTED = 4


@dataclass
class TrustPolicy:
    """Defines the trust evaluation policy parameters."""

    cert_max_age_days: int = 365
    last_seen_freshness_hours: int = 24
    credential_expiry_warning_days: int = 30
    require_attestation: bool = True
    require_valid_cert: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "cert_max_age_days": self.cert_max_age_days,
            "last_seen_freshness_hours": self.last_seen_freshness_hours,
            "credential_expiry_warning_days": self.credential_expiry_warning_days,
            "require_attestation": self.require_attestation,
            "require_valid_cert": self.require_valid_cert,
        }


@dataclass
class TrustEvaluation:
    """Result of a trust evaluation for a single node."""

    node_id: str
    level: TrustLevel
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "level": self.level.name.lower(),
            "level_value": int(self.level),
            "reasons": self.reasons,
        }


# ── Trust requirements per operation ─────────────────────────────────

TRUST_REQUIREMENTS: dict[str, TrustLevel] = {
    # Read-only / monitoring
    "read_inventory": TrustLevel.ENROLLED,
    "read_status": TrustLevel.ENROLLED,
    "heartbeat": TrustLevel.ENROLLED,
    # Sync and config
    "sync_branding": TrustLevel.ATTESTED,
    "sync_config": TrustLevel.ATTESTED,
    "register_node": TrustLevel.ATTESTED,
    # Remote execution
    "execute_remote_action": TrustLevel.VERIFIED,
    "restart_service": TrustLevel.VERIFIED,
    "create_backup": TrustLevel.VERIFIED,
    # Credential and admin operations
    "rotate_credentials": TrustLevel.TRUSTED,
    "install_app": TrustLevel.TRUSTED,
    "remove_app": TrustLevel.TRUSTED,
    "upgrade_app": TrustLevel.TRUSTED,
    "restore_backup": TrustLevel.TRUSTED,
    "system_upgrade": TrustLevel.TRUSTED,
    "execute_failover": TrustLevel.TRUSTED,
}


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO8601 timestamp, returning None on failure."""

    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return None


def _is_revoked(node_id: str, certs_dir: str | Path) -> bool:
    """Check whether a node appears in the local CRL."""

    crl_path = Path(certs_dir) / "fleet-crl.json"
    if not crl_path.exists():
        return False
    try:
        payload = json.loads(crl_path.read_text(encoding="utf-8"))
        return any(
            entry.get("node_id") == node_id for entry in payload.get("revoked", [])
        )
    except (json.JSONDecodeError, OSError):
        return True  # Assume revoked if CRL is unreadable


def _cert_exists(node_id: str, certs_dir: str | Path) -> bool:
    """Check whether a node certificate file exists."""

    return (Path(certs_dir) / f"{node_id}.crt").exists()


def evaluate_trust(
    node_record: dict[str, Any],
    certs_dir: str | Path,
    *,
    policy: TrustPolicy | None = None,
) -> TrustEvaluation:
    """Evaluate the trust level of a node based on its record and certificate state.

    Checks performed (in order of increasing trust):
    1. Enrollment status
    2. Attestation status
    3. Certificate validity and CRL status
    4. Last-seen freshness
    5. Credential expiry proximity

    Returns a TrustEvaluation with the computed level and explanatory reasons.
    """

    pol = policy or TrustPolicy()
    node_id = str(node_record.get("node_id", ""))
    reasons: list[str] = []
    now = datetime.now(timezone.utc)

    # ── Check 1: revocation ──────────────────────────────────────────
    if (
        node_record.get("credential_revoked_at")
        or node_record.get("status") == "revoked"
    ):
        reasons.append("node credentials are revoked")
        return TrustEvaluation(
            node_id=node_id, level=TrustLevel.UNTRUSTED, reasons=reasons
        )

    if _is_revoked(node_id, certs_dir):
        reasons.append("node is listed in certificate revocation list")
        return TrustEvaluation(
            node_id=node_id, level=TrustLevel.UNTRUSTED, reasons=reasons
        )

    # ── Check 2: enrollment ──────────────────────────────────────────
    status = str(node_record.get("status", ""))
    if status in {"", "discovered", "bootstrap_pending"}:
        reasons.append(f"node status is '{status or 'unknown'}' — not yet enrolled")
        return TrustEvaluation(
            node_id=node_id, level=TrustLevel.UNTRUSTED, reasons=reasons
        )

    reasons.append("node is enrolled")
    level = TrustLevel.ENROLLED

    # ── Check 3: attestation ─────────────────────────────────────────
    attested_at = _parse_iso(node_record.get("attested_at"))
    _enrolled_at = _parse_iso(node_record.get("enrolled_at"))
    if attested_at or status in {"attested", "healthy", "degraded", "draining"}:
        reasons.append("node attestation completed")
        level = TrustLevel.ATTESTED
    elif pol.require_attestation:
        reasons.append("attestation required but not completed")
        return TrustEvaluation(node_id=node_id, level=level, reasons=reasons)

    # ── Check 4: certificate validity ────────────────────────────────
    cert_valid = True
    if pol.require_valid_cert:
        if not _cert_exists(node_id, certs_dir):
            reasons.append("node certificate file not found")
            cert_valid = False
        else:
            expires_at = _parse_iso(node_record.get("credential_expires_at"))
            if expires_at and expires_at < now:
                reasons.append("node certificate has expired")
                cert_valid = False
            elif expires_at:
                days_remaining = (expires_at - now).days
                if days_remaining < pol.credential_expiry_warning_days:
                    reasons.append(f"certificate expires in {days_remaining} days")
                else:
                    reasons.append("certificate is valid")

    if cert_valid:
        reasons.append("certificate verification passed")
        level = TrustLevel.VERIFIED
    else:
        return TrustEvaluation(node_id=node_id, level=level, reasons=reasons)

    # ── Check 5: last-seen freshness ─────────────────────────────────
    last_seen = _parse_iso(node_record.get("last_seen"))
    if last_seen:
        staleness = now - last_seen
        if staleness > timedelta(hours=pol.last_seen_freshness_hours):
            reasons.append(
                f"node last seen {staleness.total_seconds() / 3600:.1f}h ago (threshold: {pol.last_seen_freshness_hours}h)"
            )
            return TrustEvaluation(node_id=node_id, level=level, reasons=reasons)
        reasons.append("node recently active")
        level = TrustLevel.TRUSTED
    elif status in {"healthy"}:
        # No last_seen but healthy status implies recent activity
        reasons.append("node status is healthy (no explicit last_seen)")
        level = TrustLevel.TRUSTED
    else:
        reasons.append("no last_seen timestamp available")

    return TrustEvaluation(node_id=node_id, level=level, reasons=reasons)


def check_operation_allowed(
    node_record: dict[str, Any],
    certs_dir: str | Path,
    operation: str,
    *,
    policy: TrustPolicy | None = None,
) -> dict[str, Any]:
    """Check whether a node is trusted enough to perform a given operation.

    Returns a dict with 'allowed', 'node_trust', 'required_trust', and 'reasons'.
    """

    required = TRUST_REQUIREMENTS.get(operation)
    if required is None:
        return {
            "allowed": False,
            "operation": operation,
            "error": f"unknown operation: {operation}",
        }

    evaluation = evaluate_trust(node_record, certs_dir, policy=policy)
    allowed = evaluation.level >= required
    return {
        "allowed": allowed,
        "operation": operation,
        "node_trust": evaluation.level.name.lower(),
        "node_trust_value": int(evaluation.level),
        "required_trust": required.name.lower(),
        "required_trust_value": int(required),
        "reasons": evaluation.reasons,
    }
