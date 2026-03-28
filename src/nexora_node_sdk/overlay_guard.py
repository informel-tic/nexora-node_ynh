"""Nexora Overlay Guard — security layer for overlay operations.

Ensures that:
1. Only the authenticated SaaS control plane can deploy/modify overlay features.
   The node agent alone CANNOT install features — it is a passive receiver.
2. Deployed features are bound to a lease (valid_until) renewed by SaaS heartbeat.
   Expired leases cause features to be stopped automatically.
3. The overlay manifest is HMAC-signed to detect tampering.
4. If a subscriber manually removes overlay files, features become unavailable.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GUARD_DIR = Path("/opt/nexora/guard")
SAAS_SECRET_PATH = GUARD_DIR / "saas_shared_secret"
MANIFEST_SIG_PATH = Path("/opt/nexora/overlay") / "manifest.sig"
TAMPER_LOG_PATH = GUARD_DIR / "tamper_events.jsonl"

DEFAULT_LEASE_SECONDS = 86400
MAX_LEASE_SECONDS = 604800
HMAC_CLOCK_SKEW_SECONDS = 300


def _ensure_guard_dir() -> None:
    GUARD_DIR.mkdir(parents=True, exist_ok=True)


def store_saas_secret(secret: str) -> None:
    _ensure_guard_dir()
    SAAS_SECRET_PATH.write_text(secret, encoding="utf-8")
    try:
        SAAS_SECRET_PATH.chmod(0o600)
    except OSError:
        pass


def load_saas_secret() -> str | None:
    if SAAS_SECRET_PATH.exists():
        return SAAS_SECRET_PATH.read_text(encoding="utf-8").strip()
    return None


def generate_saas_secret() -> str:
    return secrets.token_hex(32)


def is_enrolled() -> bool:
    secret = load_saas_secret()
    return secret is not None and len(secret) >= 32


def compute_command_hmac(
    secret: str, *, action: str, timestamp: str, payload_digest: str = "",
) -> str:
    message = f"{action}:{timestamp}:{payload_digest}"
    return hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256,
    ).hexdigest()


def verify_saas_command(
    *, action: str, timestamp: str, signature: str, payload: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    secret = load_saas_secret()
    if not secret:
        return False, "no_saas_secret_configured"
    try:
        cmd_time = datetime.fromisoformat(timestamp).timestamp()
    except (ValueError, TypeError):
        return False, "invalid_timestamp_format"
    now = time.time()
    if abs(now - cmd_time) > HMAC_CLOCK_SKEW_SECONDS:
        return False, "timestamp_expired_or_future"
    payload_digest = ""
    if payload:
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    expected = compute_command_hmac(
        secret, action=action, timestamp=timestamp, payload_digest=payload_digest,
    )
    if not hmac.compare_digest(expected, signature):
        _log_tamper_event("invalid_hmac", {"action": action, "timestamp": timestamp})
        return False, "invalid_signature"
    return True, "ok"


def sign_manifest(manifest_content: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), manifest_content.encode("utf-8"), hashlib.sha256,
    ).hexdigest()


def save_manifest_signature(manifest_content: str) -> bool:
    secret = load_saas_secret()
    if not secret:
        return False
    sig = sign_manifest(manifest_content, secret)
    MANIFEST_SIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_SIG_PATH.write_text(sig, encoding="utf-8")
    try:
        MANIFEST_SIG_PATH.chmod(0o600)
    except OSError:
        pass
    return True


def verify_manifest_integrity() -> tuple[bool, str]:
    manifest_path = Path("/opt/nexora/overlay/manifest.json")
    if not manifest_path.exists():
        return True, "no_manifest"
    if not MANIFEST_SIG_PATH.exists():
        return False, "missing_signature_file"
    secret = load_saas_secret()
    if not secret:
        return False, "no_saas_secret"
    manifest_content = manifest_path.read_text(encoding="utf-8")
    stored_sig = MANIFEST_SIG_PATH.read_text(encoding="utf-8").strip()
    expected_sig = sign_manifest(manifest_content, secret)
    if hmac.compare_digest(stored_sig, expected_sig):
        return True, "ok"
    _log_tamper_event("manifest_tampered", {"manifest_path": str(manifest_path)})
    return False, "manifest_tampered"


def compute_lease_expiry(seconds: int = DEFAULT_LEASE_SECONDS) -> str:
    clamped = min(seconds, MAX_LEASE_SECONDS)
    expiry = datetime.now(timezone.utc).timestamp() + clamped
    return datetime.fromtimestamp(expiry, tz=timezone.utc).isoformat()


def is_lease_valid(valid_until: str | None) -> bool:
    if not valid_until:
        return False
    try:
        expiry = datetime.fromisoformat(valid_until).timestamp()
    except (ValueError, TypeError):
        return False
    return time.time() < expiry


def renew_all_leases(
    manifest: dict[str, Any], lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, Any]:
    new_expiry = compute_lease_expiry(lease_seconds)
    for comp in manifest.get("components", []):
        comp["valid_until"] = new_expiry
    manifest["lease_renewed_at"] = datetime.now(timezone.utc).isoformat()
    return manifest


def find_expired_components(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in manifest.get("components", []) if not is_lease_valid(c.get("valid_until"))]


def check_overlay_file_integrity(manifest: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    for comp in manifest.get("components", []):
        detail = comp.get("detail", {})
        kind, name = comp["kind"], comp["name"]
        if kind == "docker-service":
            p = detail.get("compose_path")
            if p and not Path(p).exists():
                issues.append({"kind": kind, "name": name, "issue": "compose_file_missing", "expected_path": p})
        elif kind == "nginx-snippet":
            p = detail.get("path")
            if p and not Path(p).exists():
                issues.append({"kind": kind, "name": name, "issue": "nginx_snippet_missing", "expected_path": p})
        elif kind == "systemd":
            p = detail.get("unit")
            if p and not Path(p).exists():
                issues.append({"kind": kind, "name": name, "issue": "systemd_unit_missing", "expected_path": p})
        elif kind == "cron":
            p = detail.get("path")
            if p and not Path(p).exists():
                issues.append({"kind": kind, "name": name, "issue": "cron_file_missing", "expected_path": p})
    tampered = len(issues) > 0
    if tampered:
        _log_tamper_event("file_integrity_violation", {"issues": issues})
    return {
        "integrity_ok": not tampered,
        "checked_components": len(manifest.get("components", [])),
        "issues": issues,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _log_tamper_event(event_type: str, details: dict[str, Any]) -> None:
    _ensure_guard_dir()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "details": details,
    }
    try:
        with open(TAMPER_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("Failed to write tamper event: %s", event_type)


def get_tamper_events(limit: int = 50) -> list[dict[str, Any]]:
    if not TAMPER_LOG_PATH.exists():
        return []
    events = []
    try:
        lines = TAMPER_LOG_PATH.read_text(encoding="utf-8").strip().split("\n")
        for line in lines[-limit:]:
            if line.strip():
                events.append(json.loads(line))
    except (OSError, json.JSONDecodeError):
        pass
    return events


def guard_status() -> dict[str, Any]:
    enrolled = is_enrolled()
    manifest_ok, manifest_reason = verify_manifest_integrity()
    return {
        "enrolled": enrolled,
        "saas_secret_present": load_saas_secret() is not None,
        "manifest_integrity": {"valid": manifest_ok, "reason": manifest_reason},
        "tamper_events_count": len(get_tamper_events(limit=1000)),
        "guard_dir": str(GUARD_DIR),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
