"""Token management: loading, rotation, session tokens, auto-rotation.

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
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Token file path resolution ────────────────────────────────────────

_DEFAULT_TOKEN_PATH_CANDIDATES = [
    "/etc/nexora/api-token",
    "/opt/nexora/var/api-token",
]


def _token_path_candidates() -> list[str]:
    return [
        os.environ.get("NEXORA_API_TOKEN_FILE", ""),
        *_DEFAULT_TOKEN_PATH_CANDIDATES,
    ]


def _token_scope_path_candidates() -> list[str]:
    return [
        os.environ.get("NEXORA_API_TOKEN_SCOPE_FILE", ""),
        "/etc/nexora/api-token-scopes.json",
        "/opt/nexora/var/api-token-scopes.json",
    ]


def _token_role_path_candidates() -> list[str]:
    return [
        os.environ.get("NEXORA_API_TOKEN_ROLE_FILE", ""),
        "/etc/nexora/api-token-roles.json",
        "/opt/nexora/var/api-token-roles.json",
    ]


# ── Token loading & generation ────────────────────────────────────────


def _load_or_generate_token() -> str:
    """Load token from file or generate one on first use."""
    for path_str in _token_path_candidates():
        if not path_str:
            continue
        path = Path(path_str)
        if path.exists():
            token = path.read_text().strip()
            if token:
                return token

    # Generate a new token and store it
    token = secrets.token_urlsafe(32)
    for path_str in _token_path_candidates()[1:]:
        path = Path(path_str)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(token)
            path.chmod(0o600)
            return token
        except (OSError, PermissionError):
            continue

    # Fallback: keep in memory only (logs a warning)
    return token


_api_token: Optional[str] = None


def _resolve_primary_token_path(token_file: str | Path | None = None) -> Path:
    if token_file is not None:
        return Path(token_file)

    for path_str in _token_path_candidates():
        if not path_str:
            continue
        path = Path(path_str)
        if path.exists():
            return path

    for path_str in _token_path_candidates():
        if path_str:
            return Path(path_str)

    return Path("/opt/nexora/var/api-token")


# ── Token metadata ────────────────────────────────────────────────────


def _token_meta_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.meta.json")


def _read_token_meta(path: Path) -> dict[str, Any]:
    meta_path = _token_meta_path(path)
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_token_meta(path: Path, payload: dict[str, Any]) -> None:
    meta_path = _token_meta_path(path)
    try:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        meta_path.chmod(0o600)
    except OSError:
        logger.warning(
            "failed to persist API token metadata", extra={"path": str(meta_path)}
        )


# ── Token rotation ────────────────────────────────────────────────────


def rotate_api_token(
    *, reason: str = "manual", token_file: str | Path | None = None
) -> dict[str, Any]:
    """Rotate the API token and persist rotation metadata."""

    global _api_token
    previous = get_api_token()
    new_token = secrets.token_urlsafe(32)
    token_path = _resolve_primary_token_path(token_file)

    backup_path: str | None = None
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        if token_path.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = token_path.with_name(f"{token_path.name}.bak-{stamp}")
            backup.write_text(token_path.read_text(encoding="utf-8"), encoding="utf-8")
            backup.chmod(0o600)
            backup_path = str(backup)
        token_path.write_text(new_token, encoding="utf-8")
        token_path.chmod(0o600)
    except OSError as exc:
        return {"rotated": False, "error": str(exc), "path": str(token_path)}

    rotated_at = datetime.now(timezone.utc).isoformat()
    _write_token_meta(
        token_path,
        {
            "rotated_at": rotated_at,
            "reason": reason,
            "token_digest": hashlib.sha256(new_token.encode("utf-8")).hexdigest(),
        },
    )

    _api_token = new_token
    logger.info("API token rotated", extra={"path": str(token_path), "reason": reason})
    return {
        "rotated": True,
        "path": str(token_path),
        "backup_path": backup_path,
        "rotated_at": rotated_at,
        "reason": reason,
        "previous_token_digest": hashlib.sha256(previous.encode("utf-8")).hexdigest(),
        "token_digest": hashlib.sha256(new_token.encode("utf-8")).hexdigest(),
    }


def _maybe_auto_rotate_token() -> None:
    """Optionally rotate API token when metadata age exceeds configured days."""

    raw = os.environ.get("NEXORA_API_TOKEN_AUTO_ROTATE_DAYS", "0").strip()
    try:
        rotate_days = int(raw)
    except ValueError:
        rotate_days = 0
    if rotate_days <= 0:
        return

    token_path = _resolve_primary_token_path()
    meta = _read_token_meta(token_path)
    now = datetime.now(timezone.utc)
    rotated_at_raw = str(meta.get("rotated_at") or "").strip()
    if not rotated_at_raw:
        _write_token_meta(
            token_path,
            {
                "rotated_at": now.isoformat(),
                "reason": "initialize-auto-rotation-metadata",
                "token_digest": hashlib.sha256(
                    get_api_token().encode("utf-8")
                ).hexdigest(),
            },
        )
        return
    try:
        rotated_at = datetime.fromisoformat(rotated_at_raw)
    except ValueError:
        return
    if (now - rotated_at).days >= rotate_days:
        rotate_api_token(reason=f"auto-rotation-{rotate_days}d", token_file=token_path)


# ── Token accessor and session helpers ───────────────────────────────


def get_api_token() -> str:
    global _api_token
    if _api_token is None:
        _api_token = _load_or_generate_token()
        _maybe_auto_rotate_token()
        _api_token = _load_or_generate_token()
    return _api_token


def generate_session_token(*, max_age_seconds: int = 3600) -> dict[str, Any]:
    """Generate a session token payload with explicit max age metadata."""

    return {
        "session_token": secrets.token_urlsafe(32),
        "issued_at": int(time.time()),
        "max_age_seconds": int(max_age_seconds),
    }


def validate_session_age(issued_at: str | int, *, max_age: int = 3600) -> bool:
    """Return whether a session timestamp is still inside the allowed age."""

    try:
        issued_ts = int(str(issued_at).strip())
    except (TypeError, ValueError):
        return False
    return (int(time.time()) - issued_ts) <= int(max_age)
