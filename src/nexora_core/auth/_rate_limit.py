"""Auth failure rate limiting with file-backed persistence across restarts.

Part of the nexora_core.auth package.  All symbols here are re-exported
from nexora_core.auth.__init__ for backward compatibility.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_AUTH_FAILURES: dict[str, list[float]] = defaultdict(list)
_MAX_AUTH_FAILURES = 10
_AUTH_WINDOW_SECONDS = 300


def _auth_runtime_file() -> Path:
    explicit = os.environ.get("NEXORA_AUTH_RUNTIME_FILE", "").strip()
    if explicit:
        return Path(explicit)
    state_hint = os.environ.get("NEXORA_STATE_PATH", "").strip()
    if state_hint:
        return Path(state_hint).with_name("auth-runtime.json")
    return Path("/opt/nexora/var/auth-runtime.json")


def _load_auth_runtime_payload() -> dict[str, Any]:
    path = _auth_runtime_file()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_auth_runtime_payload(payload: dict[str, Any]) -> None:
    path = _auth_runtime_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        path.chmod(0o600)
    except OSError:
        logger.warning(
            "failed to persist auth runtime payload", extra={"path": str(path)}
        )


def _merge_persisted_failures(client_ip: str) -> None:
    payload = _load_auth_runtime_payload()
    persisted = payload.get("auth_failures", {})
    if not isinstance(persisted, dict):
        return
    entries = persisted.get(client_ip, [])
    if not isinstance(entries, list):
        return
    now = time.time()
    current = _AUTH_FAILURES.get(client_ip, [])
    merged = [float(ts) for ts in current if now - float(ts) < _AUTH_WINDOW_SECONDS]
    for ts in entries:
        try:
            ts_val = float(ts)
        except (TypeError, ValueError):
            continue
        if now - ts_val < _AUTH_WINDOW_SECONDS:
            merged.append(ts_val)
    _AUTH_FAILURES[client_ip] = sorted(set(merged))


def _persist_failures(client_ip: str) -> None:
    payload = _load_auth_runtime_payload()
    auth_failures = payload.get("auth_failures", {})
    if not isinstance(auth_failures, dict):
        auth_failures = {}
    auth_failures[client_ip] = list(_AUTH_FAILURES.get(client_ip, []))
    payload["auth_failures"] = auth_failures
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_auth_runtime_payload(payload)


def _check_rate_limit(client_ip: str) -> bool:
    """Return True if the client is rate-limited (too many auth failures)."""
    _merge_persisted_failures(client_ip)
    now = time.time()
    failures = _AUTH_FAILURES[client_ip]
    # Prune old entries.
    _AUTH_FAILURES[client_ip] = [t for t in failures if now - t < _AUTH_WINDOW_SECONDS]
    _persist_failures(client_ip)
    return len(_AUTH_FAILURES[client_ip]) >= _MAX_AUTH_FAILURES


def _record_auth_failure(client_ip: str) -> None:
    _AUTH_FAILURES[client_ip].append(time.time())
    _persist_failures(client_ip)
