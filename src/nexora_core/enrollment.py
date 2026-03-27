"""Enrollment token issuance and node attestation helpers.

This module implements TASK-3-1-3-1, TASK-3-1-3-2 and TASK-3-1-5-1 by
providing one-time enrollment tokens, challenge-response attestation helpers,
and append-only audit events persisted in the JSON state store.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .compatibility import assess_compatibility, load_compatibility_matrix

_CLOCK_SKEW_TOLERANCE_SECONDS = 300


def _utc_now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    """Serialize a timezone-aware datetime as ISO8601."""

    return value.isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO8601 timestamp if present."""

    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _token_digest(token: str) -> str:
    """Hash a plaintext token for durable storage."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _append_event(
    state: dict[str, Any], event: dict[str, Any], tenant_id: str | None = None
) -> None:
    """Append an enrollment/security event to the mutable state."""

    event_record = {**event}
    if tenant_id:
        event_record["tenant_id"] = tenant_id

    state.setdefault("enrollment_events", []).append(event_record)
    state.setdefault("security_audit", []).append(
        {"category": "enrollment", **event_record}
    )


# TASK-3-1-3-1: Enrollment API.
def issue_enrollment_token(
    state: dict[str, Any],
    *,
    requested_by: str,
    mode: str,
    ttl_minutes: int = 30,
    node_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Issue a one-time enrollment token and store only its digest in state."""

    if mode not in {"push", "pull"}:
        raise ValueError(f"Unsupported enrollment mode: {mode}")
    if ttl_minutes <= 0:
        raise ValueError("Enrollment token TTL must be positive")

    now = _utc_now()
    token = secrets.token_urlsafe(24)
    token_id = f"enroll-{secrets.token_hex(6)}"
    challenge = secrets.token_urlsafe(16)
    challenge_digest = _token_digest(challenge)
    record = {
        "token_id": token_id,
        "token_digest": _token_digest(token),
        "challenge_digest": challenge_digest,
        "mode": mode,
        "node_id": node_id,
        "tenant_id": tenant_id,
        "requested_by": requested_by,
        "issued_at": _iso(now),
        "expires_at": _iso(now + timedelta(minutes=ttl_minutes)),
        "consumed_at": None,
        "attested_at": None,
        "status": "issued",
    }
    state.setdefault("enrollment_tokens", []).append(record)
    _append_event(
        state,
        {
            "timestamp": _iso(now),
            "event": "token_issued",
            "token_id": token_id,
            "requested_by": requested_by,
            "mode": mode,
            "node_id": node_id,
        },
        tenant_id=tenant_id,
    )
    return {
        "token": token,
        "challenge": challenge,
        "token_id": token_id,
        "expires_at": record["expires_at"],
        "mode": mode,
        "node_id": node_id,
        "tenant_id": tenant_id,
    }


# TASK-3-1-3-2: Node attestation.
def validate_enrollment_token(
    state: dict[str, Any],
    token: str,
    *,
    expected_mode: str | None = None,
) -> dict[str, Any]:
    """Return the stored token record if it exists, is valid and unused."""

    digest = _token_digest(token)
    now = _utc_now()
    for record in state.get("enrollment_tokens", []):
        if record.get("token_digest") != digest:
            continue
        expires_at = _parse_iso(record.get("expires_at"))
        if expires_at is None or expires_at < now:
            raise ValueError("Enrollment token expired")
        if record.get("consumed_at"):
            raise ValueError("Enrollment token already consumed")
        if expected_mode and record.get("mode") != expected_mode:
            raise ValueError("Enrollment token mode mismatch")
        return record
    raise ValueError("Enrollment token not found")


# TASK-3-1-3-2: Node attestation.
def build_attestation_response(*, challenge: str, node_id: str, token_id: str) -> str:
    """Build the deterministic challenge-response proof sent by the node."""

    material = f"{challenge}:{node_id}:{token_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


# TASK-3-1-3-2: Node attestation.
def attest_node(
    state: dict[str, Any],
    *,
    token: str,
    challenge: str,
    challenge_response: str,
    hostname: str,
    node_id: str,
    agent_version: str,
    yunohost_version: str | None,
    debian_version: str | None,
    observed_at: str,
    compatibility_matrix_path: str | None = None,
) -> dict[str, Any]:
    """Validate challenge-response, freshness and version compatibility."""

    record = validate_enrollment_token(state, token)
    expected_response = build_attestation_response(
        challenge=challenge,
        node_id=node_id,
        token_id=str(record.get("token_id")),
    )
    if not secrets.compare_digest(expected_response, challenge_response):
        raise ValueError("Attestation challenge response mismatch")
    if record.get("challenge_digest") != _token_digest(challenge):
        raise ValueError("Attestation challenge unknown or stale")

    observed = _parse_iso(observed_at)
    if observed is None:
        raise ValueError("Invalid attestation timestamp")
    skew = abs((_utc_now() - observed).total_seconds())
    if skew > _CLOCK_SKEW_TOLERANCE_SECONDS:
        raise ValueError("Attestation timestamp exceeds clock skew tolerance")

    compatibility = assess_compatibility(
        agent_version,
        yunohost_version,
        matrix=load_compatibility_matrix(compatibility_matrix_path)
        if compatibility_matrix_path
        else None,
    )
    if not compatibility.get("bootstrap_allowed"):
        raise ValueError(
            "Attestation rejected due to compatibility policy: "
            + ", ".join(compatibility.get("reasons", []) or ["unknown"])
        )

    record["attested_at"] = _iso(_utc_now())
    record["status"] = "attested"
    _append_event(
        state,
        {
            "timestamp": record["attested_at"],
            "event": "node_attested",
            "token_id": record.get("token_id"),
            "node_id": node_id,
            "hostname": hostname,
            "agent_version": agent_version,
            "yunohost_version": yunohost_version,
            "debian_version": debian_version,
        },
        tenant_id=record.get("tenant_id"),
    )
    return {
        "token_id": record.get("token_id"),
        "status": "attested",
        "hostname": hostname,
        "node_id": node_id,
        "tenant_id": record.get("tenant_id"),
        "compatibility": compatibility,
    }


# TASK-3-1-3-3: Remote management activation post-attestation.
def consume_enrollment_token(
    state: dict[str, Any], token: str, *, node_id: str
) -> dict[str, Any]:
    """Mark an attested token as consumed and ready for registration."""

    record = validate_enrollment_token(state, token)
    if record.get("status") != "attested":
        raise ValueError("Enrollment token must be attested before registration")
    record["consumed_at"] = _iso(_utc_now())
    record["status"] = "consumed"
    record["node_id"] = node_id
    _append_event(
        state,
        {
            "timestamp": record["consumed_at"],
            "event": "token_consumed",
            "token_id": record.get("token_id"),
            "node_id": node_id,
        },
        tenant_id=record.get("tenant_id"),
    )
    return record
