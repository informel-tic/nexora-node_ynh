"""Trust policy engine for control-plane ↔ node-agent communication.

WS4-T01: Defines the trust model that governs whether a node is allowed to
participate in fleet operations.  Every remote call from the control plane
to a node agent (and vice-versa) must pass through ``verify_node_trust``
before any business logic executes.

Trust levels
────────────
  untrusted   – node has no valid credentials or has been revoked
  provisional – node is enrolled but not yet fully attested
  trusted     – node holds a valid, non-expired, non-revoked identity
  elevated    – node holds valid identity *and* operator escalation token

Policy rules are evaluated in order; the first failing rule short-circuits
and returns the denial reason.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from .tls import is_certificate_revoked

# ── Trust levels ─────────────────────────────────────────────────────

TRUST_LEVELS = ("untrusted", "provisional", "trusted", "elevated")

# Minimum trust level required per action category.
ACTION_TRUST_REQUIREMENTS: dict[str, str] = {
    "read_inventory": "provisional",
    "sync_branding": "trusted",
    "execute_remote_action": "trusted",
    "rotate_credentials": "trusted",
    "lifecycle_admin": "elevated",
    "fleet_topology": "trusted",
    "pra_snapshot": "trusted",
    "healthcheck": "provisional",
}

# Statuses that imply an active, trustable node.
_ACTIVE_STATUSES = {"attested", "registered", "healthy", "degraded", "draining"}
_PROVISIONAL_STATUSES = {"bootstrap_pending", "agent_installed"}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Core trust evaluation ────────────────────────────────────────────


def evaluate_trust_level(
    node: dict[str, Any],
    *,
    certs_dir: str | None = None,
) -> str:
    """Compute the current trust level of a node based on its record.

    Returns one of the ``TRUST_LEVELS`` strings.
    """
    status = str(node.get("status") or "discovered")

    # Hard deny: revoked or retired nodes are untrusted.
    if status in {"revoked", "retired"}:
        return "untrusted"

    # CRL check if certs_dir is available.
    node_id = str(node.get("node_id") or "")
    if certs_dir and node_id and is_certificate_revoked(certs_dir, node_id):
        return "untrusted"

    # Credential expiry check.
    expires_at = _parse_iso(node.get("credential_expires_at"))
    if expires_at is not None and expires_at < _utc_now():
        return "untrusted"

    # Revocation flag in record.
    if node.get("credential_revoked_at"):
        return "untrusted"

    # Provisional: enrolled but not yet attested/registered.
    if status in _PROVISIONAL_STATUSES:
        return "provisional"

    # Discovered with no credentials yet.
    if status == "discovered":
        return "untrusted"

    # Active node with valid credentials.
    if status in _ACTIVE_STATUSES:
        # Elevated if an active escalation token is present.
        escalation_expires = _parse_iso(node.get("escalation_expires_at"))
        if escalation_expires and escalation_expires > _utc_now():
            return "elevated"
        return "trusted"

    return "untrusted"


def _trust_rank(level: str) -> int:
    """Return a numeric rank for comparison."""
    try:
        return TRUST_LEVELS.index(level)
    except ValueError:
        return -1


def verify_node_trust(
    node: dict[str, Any],
    *,
    required_action: str,
    certs_dir: str | None = None,
) -> dict[str, Any]:
    """Gate-check: verify that *node* meets the trust requirement for *action*.

    Returns a dict with ``allowed`` (bool), ``trust_level``, and optionally
    ``denial_reason``.
    """
    current_level = evaluate_trust_level(node, certs_dir=certs_dir)
    required_level = ACTION_TRUST_REQUIREMENTS.get(required_action, "trusted")
    allowed = _trust_rank(current_level) >= _trust_rank(required_level)

    result: dict[str, Any] = {
        "allowed": allowed,
        "trust_level": current_level,
        "required_level": required_level,
        "action": required_action,
        "node_id": node.get("node_id"),
    }
    if not allowed:
        result["denial_reason"] = (
            f"Node trust level '{current_level}' is insufficient for action "
            f"'{required_action}' (requires '{required_level}')"
        )
    return result


def build_trust_challenge(node_id: str) -> dict[str, str]:
    """Issue a one-time trust challenge for mutual authentication.

    The control plane sends this challenge; the node must return a valid
    response (HMAC or signed proof) before being granted ``trusted`` level.
    """
    nonce = secrets.token_urlsafe(24)
    return {
        "node_id": node_id,
        "nonce": nonce,
        "issued_at": _utc_now().isoformat(),
    }
