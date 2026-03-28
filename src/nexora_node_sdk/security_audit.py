"""Security audit trail helpers for Nexora.

Implements append-only security events used by enrollment, TLS and auth flows,
plus WS4-T05 SecurityJournal with HMAC-based tamper detection and retention
policies.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
import secrets
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "CRITICAL_ACTIONS",
    "SECURITY_CATEGORIES",
    "SECURITY_SEVERITIES",
    "VALID_CATEGORIES",
    "VALID_SEVERITIES",
    "SecurityJournal",
    "append_security_event",
    "append_security_event_to_file",
    "build_security_event",
    "emit_security_event",
    "filter_security_events",
    "summarize_security_events",
]

# ── Well-known categories and severities ─────────────────────────────

SECURITY_CATEGORIES = {
    "enrollment",
    "tls",
    "auth",
    "identity",
    "lifecycle",
    "sync",
    "secret",
    "trust",
    "csrf",
    "session",
    "mtls",
    "revocation",
}

SECURITY_SEVERITIES = {"info", "warning", "error", "critical"}

# Actions that MUST produce a critical-severity audit event.
CRITICAL_ACTIONS = {
    "credential_revoked",
    "node_revoked",
    "node_retired",
    "trust_denied",
    "token_replay_detected",
    "csrf_violation",
    "secret_revoked",
    "unauthorized_access",
    "clock_skew_exceeded",
    "certificate_expired",
    "mtls_handshake_refused",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO8601 format."""

    return _utc_now().isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO8601 timestamp, returning None on failure."""

    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return None


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO8601 timestamp, returning None on failure."""

    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return None


# TASK-3-2-3-2 / TASK-3-15-3-1 / WS4-T05 / WS9-T02: Security audit trail.
def build_security_event(
    category: str,
    action: str,
    *,
    severity: str = "info",
    tenant_id: str | None = None,
    **details: Any,
) -> dict[str, Any]:
    """Build a structured security event payload."""

    # Auto-elevate severity for known critical actions.
    if action in CRITICAL_ACTIONS and severity not in {"error", "critical"}:
        severity = "critical"

    event = {
        "timestamp": _utc_now_iso(),
        "category": category,
        "action": action,
        "severity": severity,
        "details": details,
    }
    if tenant_id:
        event["tenant_id"] = tenant_id
    return event


# TASK-3-2-3-2 / TASK-3-15-3-1: Security audit trail.
def append_security_event(
    state: dict[str, Any], event: dict[str, Any]
) -> dict[str, Any]:
    """Append a security event to the mutable application state."""

    state.setdefault("security_audit", []).append(event)
    return event


# WS4-T05: Unified emit — in-memory + optional file sink.
def emit_security_event(
    state: dict[str, Any],
    category: str,
    action: str,
    *,
    severity: str = "info",
    state_path: str | Path | None = None,
    tenant_id: str | None = None,
    **details: Any,
) -> dict[str, Any]:
    """Build, append to state, and optionally persist a security event.

    This is the preferred entry-point for all security logging.
    """
    event = build_security_event(
        category, action, severity=severity, tenant_id=tenant_id, **details
    )
    append_security_event(state, event)

    if state_path:
        try:
            append_security_event_to_file(state_path, event)
        except Exception as exc:
            logger.warning(
                "Failed to persist security event to %s: %s", state_path, exc
            )

    return event


# TASK-3-15-3-1: Security audit trail.
def append_security_event_to_file(
    state_path: str | Path, event: dict[str, Any]
) -> dict[str, Any]:
    """Append a security event to the JSON state file."""

    path = Path(state_path)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    append_security_event(data, event)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return event


# TASK-3-2-3-2: Security channel audit logging.
def summarize_security_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize security events by category and severity."""

    categories: dict[str, int] = {}
    severities: dict[str, int] = {}
    for event in events:
        category = str(event.get("category") or "unknown")
        severity = str(event.get("severity") or "info")
        categories[category] = categories.get(category, 0) + 1
        severities[severity] = severities.get(severity, 0) + 1

    critical_events = [e for e in events if e.get("severity") == "critical"]

    return {
        "total_events": len(events),
        "categories": categories,
        "severities": severities,
        "critical_events": len(critical_events),
        "latest_event": events[-1] if events else None,
    }


def filter_security_events(
    events: list[dict[str, Any]],
    *,
    category: str | None = None,
    severity: str | None = None,
    action: str | None = None,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return security events filtered by optional predicates."""

    filtered: list[dict[str, Any]] = []
    for event in events:
        if category is not None and event.get("category") != category:
            continue
        if severity is not None and event.get("severity") != severity:
            continue
        if action is not None and event.get("action") != action:
            continue
        if tenant_id is not None and event.get("tenant_id") != tenant_id:
            continue
        filtered.append(event)
    return filtered


# ── WS4-T05: Security event journaling with HMAC integrity ──────────

VALID_SEVERITIES = {"debug", "info", "warning", "error", "critical"}
VALID_CATEGORIES = {
    "auth",
    "tls",
    "enrollment",
    "credential",
    "trust",
    "lifecycle",
    "access",
    "config",
    "system",
    "audit",
}


class SecurityJournal:
    """Append-only security event journal with HMAC-based integrity chain.

    Each event receives:
    - ``event_id``: a unique UUID
    - ``prev_hash``: SHA-256 of the previous event's serialized form (empty string for first)
    - ``hmac``: HMAC-SHA256 of the event body using the journal's signing key

    The chain of prev_hash + hmac values allows detecting tampering or
    insertion/deletion of events.
    """

    def __init__(
        self,
        journal_path: str | Path,
        *,
        signing_key: str | bytes | None = None,
    ):
        self._path = Path(journal_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

        if signing_key is None:
            # Generate and persist a signing key
            key_path = self._path.parent / f"{self._path.stem}.key"
            if key_path.exists():
                self._signing_key = key_path.read_bytes()
            else:
                self._signing_key = secrets.token_bytes(32)
                key_path.write_bytes(self._signing_key)
                try:
                    key_path.chmod(0o600)
                except OSError:
                    pass
        elif isinstance(signing_key, str):
            self._signing_key = signing_key.encode("utf-8")
        else:
            self._signing_key = signing_key

        self._events: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        """Load existing events from the journal file."""

        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._events = (
                    data if isinstance(data, list) else data.get("events", [])
                )
            except (json.JSONDecodeError, OSError):
                self._events = []

    def _save(self) -> None:
        """Persist events to the journal file."""

        self._path.write_text(
            json.dumps(self._events, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            self._path.chmod(0o600)
        except OSError:
            pass

    def _compute_event_hash(self, event: dict[str, Any]) -> str:
        """Compute SHA-256 hash of a serialized event (excluding hmac and prev_hash)."""

        # Deterministic serialization of the event content
        content = {k: v for k, v in event.items() if k not in ("hmac", "prev_hash")}
        serialized = json.dumps(content, sort_keys=True, ensure_ascii=False).encode(
            "utf-8"
        )
        return hashlib.sha256(serialized).hexdigest()

    def _compute_hmac(self, event: dict[str, Any]) -> str:
        """Compute HMAC-SHA256 of the event including prev_hash but excluding hmac."""

        content = {k: v for k, v in event.items() if k != "hmac"}
        serialized = json.dumps(content, sort_keys=True, ensure_ascii=False).encode(
            "utf-8"
        )
        return _hmac.new(self._signing_key, serialized, hashlib.sha256).hexdigest()

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def log(
        self,
        category: str,
        action: str,
        severity: str = "info",
        tenant_id: str | None = None,
        **details: Any,
    ) -> dict[str, Any]:
        """Log a security event with HMAC integrity.

        Args:
            category: Event category (auth, tls, enrollment, etc.).
            action: Specific action within the category.
            severity: One of debug, info, warning, error, critical.
            **details: Additional key-value pairs for the event.

        Returns:
            The complete event dict with event_id, prev_hash, and hmac.
        """

        if severity not in VALID_SEVERITIES:
            raise ValueError(
                f"Invalid severity: {severity}. Must be one of {VALID_SEVERITIES}"
            )

        # Compute prev_hash from last event
        if self._events:
            prev_hash = self._compute_event_hash(self._events[-1])
        else:
            prev_hash = hashlib.sha256(b"genesis").hexdigest()

        event: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "timestamp": _utc_now_iso(),
            "category": category,
            "action": action,
            "severity": severity,
            "details": details,
            "prev_hash": prev_hash,
        }
        if tenant_id:
            event["tenant_id"] = tenant_id

        # Compute HMAC over the event (including prev_hash)
        event["hmac"] = self._compute_hmac(event)

        self._events.append(event)
        self._save()
        return event

    def verify_integrity(
        self, events: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Verify the HMAC chain integrity of the event journal.

        Returns:
            Dict with ``valid``, ``verified_count``, ``errors``, and ``first_invalid_index``.
        """

        evts = events if events is not None else self._events
        errors: list[str] = []
        first_invalid: int | None = None

        for i, event in enumerate(evts):
            # Verify HMAC
            expected_hmac = self._compute_hmac(event)
            stored_hmac = event.get("hmac", "")
            if not _hmac.compare_digest(expected_hmac, stored_hmac):
                errors.append(
                    f"event {i} ({event.get('event_id', '?')}): HMAC mismatch"
                )
                if first_invalid is None:
                    first_invalid = i
                continue

            # Verify prev_hash chain
            if i == 0:
                expected_prev = hashlib.sha256(b"genesis").hexdigest()
            else:
                expected_prev = self._compute_event_hash(evts[i - 1])

            if event.get("prev_hash") != expected_prev:
                errors.append(
                    f"event {i} ({event.get('event_id', '?')}): prev_hash chain broken"
                )
                if first_invalid is None:
                    first_invalid = i

        return {
            "valid": len(errors) == 0,
            "verified_count": len(evts),
            "errors": errors,
            "first_invalid_index": first_invalid,
        }

    def export_events(
        self,
        *,
        since: str | datetime | None = None,
        until: str | datetime | None = None,
        categories: list[str] | None = None,
        severities: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Export filtered events from the journal.

        Args:
            since: Start of time range (ISO8601 string or datetime).
            until: End of time range (ISO8601 string or datetime).
            categories: Filter by event categories.
            severities: Filter by severity levels.

        Returns:
            List of matching events.
        """

        since_dt = _parse_iso(since) if isinstance(since, str) else since
        until_dt = _parse_iso(until) if isinstance(until, str) else until

        results: list[dict[str, Any]] = []
        for event in self._events:
            ts = _parse_iso(event.get("timestamp"))

            if since_dt and ts and ts < since_dt:
                continue
            if until_dt and ts and ts > until_dt:
                continue
            if categories and event.get("category") not in categories:
                continue
            if severities and event.get("severity") not in severities:
                continue
            if tenant_id and event.get("tenant_id") != tenant_id:
                continue

            results.append(event)

        return results

    def retention_policy(
        self,
        max_age_days: int | None = None,
        max_events: int | None = None,
    ) -> dict[str, Any]:
        """Enforce retention policy by removing old or excess events.

        Events are removed from the beginning (oldest first). After pruning,
        the journal is re-saved and the chain is effectively reset for any
        events that remain.

        Args:
            max_age_days: Remove events older than this many days.
            max_events: Keep at most this many events (most recent).

        Returns:
            Dict with ``removed_count`` and ``remaining_count``.
        """

        original_count = len(self._events)
        now = _utc_now()

        if max_age_days is not None:
            cutoff = now - timedelta(days=max_age_days)
            self._events = [
                e
                for e in self._events
                if (_parse_iso(e.get("timestamp")) or now) >= cutoff
            ]

        if max_events is not None and len(self._events) > max_events:
            self._events = self._events[-max_events:]

        removed = original_count - len(self._events)
        if removed > 0:
            self._save()

        return {
            "removed_count": removed,
            "remaining_count": len(self._events),
        }

    def summarize_by_period(
        self,
        period: str = "day",
    ) -> dict[str, Any]:
        """Aggregate event counts by time period.

        Args:
            period: One of 'hour', 'day', 'week', 'month'.

        Returns:
            Dict mapping period keys to category/severity breakdowns.
        """

        buckets: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "total": 0,
                "categories": defaultdict(int),
                "severities": defaultdict(int),
            }
        )

        for event in self._events:
            ts = _parse_iso(event.get("timestamp"))
            if not ts:
                continue

            if period == "hour":
                key = ts.strftime("%Y-%m-%dT%H:00")
            elif period == "day":
                key = ts.strftime("%Y-%m-%d")
            elif period == "week":
                # ISO week number
                key = f"{ts.isocalendar()[0]}-W{ts.isocalendar()[1]:02d}"
            elif period == "month":
                key = ts.strftime("%Y-%m")
            else:
                raise ValueError(
                    f"Invalid period: {period}. Must be one of hour, day, week, month"
                )

            buckets[key]["total"] += 1
            buckets[key]["categories"][event.get("category", "unknown")] += 1
            buckets[key]["severities"][event.get("severity", "info")] += 1

        # Convert defaultdicts to regular dicts for JSON serialization
        result: dict[str, Any] = {}
        for key, bucket in sorted(buckets.items()):
            result[key] = {
                "total": bucket["total"],
                "categories": dict(bucket["categories"]),
                "severities": dict(bucket["severities"]),
            }

        return result
