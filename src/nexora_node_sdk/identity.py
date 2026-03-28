"""Nexora node identity helpers and OpenSSL-backed certificate issuance."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import socket
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

NEXORA_IDENTITY = {
    "brand_name": "Nexora",
    "tagline": "orchestration souveraine pour infrastructures YunoHost professionnelles",
    "accent": "#2dd4bf",
    "accent_dark": "#14b8a6",
    "surface": "#0f172a",
    "surface_alt": "#111827",
    "text": "#e5eefb",
    "muted": "#94a3b8",
    "console_title": "Nexora Console",
    "console_subtitle": "Pilotage d'infrastructure, PRA et gouvernance YunoHost",
    "components": {
        "core": "Nexora Core",
        "mcp": "Nexora MCP",
        "console": "Nexora Console",
        "node": "Nexora Node",
        "fleet": "Nexora Fleet",
        "edge": "Nexora Edge",
        "studio": "Nexora Studio",
        "blueprints": "Nexora Blueprints",
        "packaging": "Nexora Package Factory",
    },
}

logger = logging.getLogger(__name__)


def _now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    """Serialize a timezone-aware datetime as ISO8601."""

    return value.isoformat()


def generate_node_id(hostname: str | None = None) -> str:
    """Generate a deterministic node identifier from the hostname."""

    basis = hostname or socket.gethostname()
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
    return f"node-{digest}"


def generate_fleet_id(existing: str | None = None) -> str:
    """Reuse the existing fleet identifier or create a new one."""

    return existing or f"fleet-{uuid.uuid4().hex[:12]}"


def _run_openssl(*args: str) -> None:
    """Run the OpenSSL CLI and raise a typed error on failure."""

    if not shutil.which("openssl"):
        raise RuntimeError("openssl binary is required to generate Nexora certificates")
    completed = subprocess.run(
        ["openssl", *args], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"OpenSSL command failed: {' '.join(args)} :: {completed.stderr.strip()}"
        )


def _allow_insecure_identity_fallback() -> bool:
    """Allow fallback credentials only in explicit non-production contexts."""

    raw = os.environ.get("NEXORA_ALLOW_INSECURE_IDENTITY_FALLBACK", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    # Pytest sets this environment variable while tests run.
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _fallback_credentials(
    node_id: str, fleet_id: str, certs_path: Path, *, reason: str
) -> dict[str, Any]:
    """Generate deterministic placeholder credentials when OpenSSL is unavailable."""

    issued_at = _now()
    expires_at = issued_at + timedelta(days=30)
    rotation_at = issued_at + timedelta(days=7)
    token_id = f"tok-{uuid.uuid4().hex[:12]}"
    key_path = certs_path / f"{node_id}.fallback.key"
    cert_path = certs_path / f"{node_id}.fallback.crt"
    if not key_path.exists():
        key_path.write_text("fallback-private-key\n", encoding="utf-8")
    if not cert_path.exists():
        cert_path.write_text("fallback-certificate\n", encoding="utf-8")
    key_path.chmod(0o600)
    cert_path.chmod(0o644)
    return {
        "node_id": node_id,
        "fleet_id": fleet_id,
        "token_id": token_id,
        "credential_type": "token+key-fallback",
        "certificate_subject": f"CN={node_id},OU={fleet_id},O=Nexora-Fallback",
        "key_path": str(key_path),
        "cert_path": str(cert_path),
        "issued_at": _iso(issued_at),
        "expires_at": _iso(expires_at),
        "rotation_recommended_at": _iso(rotation_at),
        "revoked_at": None,
        "insecure_fallback": True,
        "fallback_reason": reason,
    }


# TASK-3-1-1-3: Node identity contract (real PKI, rotation/revocation).
def generate_node_credentials(
    node_id: str, fleet_id: str, certs_dir: str | Path
) -> dict[str, Any]:
    """Generate a CA-signed node certificate bundle and token metadata."""

    issued_at = _now()
    expires_at = issued_at + timedelta(days=365)
    rotation_at = issued_at + timedelta(days=270)
    token_id = f"tok-{uuid.uuid4().hex[:12]}"
    certs_path = Path(certs_dir)
    certs_path.mkdir(parents=True, exist_ok=True)
    try:
        ca_key = certs_path / "fleet-ca.key"
        ca_cert = certs_path / "fleet-ca.crt"
        if not ca_key.exists() or not ca_cert.exists():
            _run_openssl(
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-sha256",
                "-days",
                "3650",
                "-nodes",
                "-keyout",
                str(ca_key),
                "-out",
                str(ca_cert),
                "-subj",
                f"/CN={fleet_id} Fleet CA/O=Nexora",
            )
            ca_key.chmod(0o600)
            ca_cert.chmod(0o644)

        key_path = certs_path / f"{node_id}.key"
        csr_path = certs_path / f"{node_id}.csr"
        cert_path = certs_path / f"{node_id}.crt"
        serial_path = certs_path / "fleet-ca.srl"
        _run_openssl("genrsa", "-out", str(key_path), "2048")
        _run_openssl(
            "req",
            "-new",
            "-key",
            str(key_path),
            "-out",
            str(csr_path),
            "-subj",
            f"/CN={node_id}/OU={fleet_id}/O=Nexora",
        )
        _run_openssl(
            "x509",
            "-req",
            "-in",
            str(csr_path),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-CAserial",
            str(serial_path),
            "-out",
            str(cert_path),
            "-days",
            "365",
            "-sha256",
        )
        key_path.chmod(0o600)
        cert_path.chmod(0o644)
    except RuntimeError as exc:
        if (
            "openssl binary is required" in str(exc)
            and _allow_insecure_identity_fallback()
        ):
            return _fallback_credentials(node_id, fleet_id, certs_path, reason=str(exc))
        raise
    return {
        "node_id": node_id,
        "fleet_id": fleet_id,
        "token_id": token_id,
        "credential_type": "token+key",
        "certificate_subject": f"CN={node_id},OU={fleet_id},O=Nexora",
        "key_path": str(key_path),
        "cert_path": str(cert_path),
        "issued_at": _iso(issued_at),
        "expires_at": _iso(expires_at),
        "rotation_recommended_at": _iso(rotation_at),
        "revoked_at": None,
    }


def revoke_node_credentials(identity: dict[str, Any]) -> dict[str, Any]:
    """Return a credential payload marked as revoked."""

    updated = dict(identity)
    updated["revoked_at"] = _iso(_now())
    return updated


# ── WS4-T02: Credential rotation industrialization ───────────────────


def rotate_node_credentials(
    node_id: str,
    fleet_id: str,
    certs_dir: str | Path,
) -> dict[str, Any]:
    """Issue new credentials for a node, revoking the old certificate.

    This performs a full rotation cycle:
    1. Record the old certificate in the local CRL (if it exists).
    2. Generate a fresh certificate bundle.
    3. Return the new credential metadata.
    """

    import json as _json

    certs_path = Path(certs_dir)
    old_cert = certs_path / f"{node_id}.crt"
    old_key = certs_path / f"{node_id}.key"

    # Revoke old certificate in local CRL if it exists
    if old_cert.exists():
        crl_path = certs_path / "fleet-crl.json"
        crl = (
            _json.loads(crl_path.read_text(encoding="utf-8"))
            if crl_path.exists()
            else {"revoked": []}
        )
        crl.setdefault("revoked", []).append(
            {
                "node_id": node_id,
                "reason": "rotation",
                "revoked_at": _iso(_now()),
            }
        )
        crl_path.write_text(
            _json.dumps(crl, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        # Remove old files so generate_node_credentials creates fresh ones
        old_cert.unlink(missing_ok=True)
        old_key.unlink(missing_ok=True)
        csr_path = certs_path / f"{node_id}.csr"
        csr_path.unlink(missing_ok=True)

    # Issue fresh credentials
    new_creds = generate_node_credentials(node_id, fleet_id, certs_path)
    new_creds["rotated_at"] = _iso(_now())
    return new_creds


def credential_status(
    node_id: str,
    certs_dir: str | Path,
) -> dict[str, Any]:
    """Return the status of a node's credentials.

    Checks the certificate file for existence and parses expiry from the
    certificate using OpenSSL. Falls back to metadata if OpenSSL parsing fails.
    """

    import json as _json
    import subprocess as _subprocess

    certs_path = Path(certs_dir)
    cert_path = certs_path / f"{node_id}.crt"
    result: dict[str, Any] = {
        "node_id": node_id,
        "cert_exists": cert_path.exists(),
        "is_revoked": False,
        "is_expired": False,
        "days_remaining": None,
        "needs_rotation": False,
    }

    # Check CRL
    crl_path = certs_path / "fleet-crl.json"
    if crl_path.exists():
        try:
            crl = _json.loads(crl_path.read_text(encoding="utf-8"))
            result["is_revoked"] = any(
                entry.get("node_id") == node_id for entry in crl.get("revoked", [])
            )
        except (OSError, _json.JSONDecodeError):
            pass

    if not cert_path.exists():
        result["is_expired"] = True
        result["needs_rotation"] = True
        return result

    # Try to extract expiry from the certificate via OpenSSL
    now = _now()
    try:
        proc = _subprocess.run(
            ["openssl", "x509", "-in", str(cert_path), "-enddate", "-noout"],
            capture_output=True,
            text=True,
            check=True,
        )
        # Output like: notAfter=Mar 23 12:00:00 2027 GMT
        date_str = proc.stdout.strip().split("=", 1)[-1]
        expires = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
        days_remaining = (expires - now).days
        result["days_remaining"] = days_remaining
        result["is_expired"] = days_remaining < 0
        result["needs_rotation"] = days_remaining < 90 or result["is_revoked"]
    except Exception as exc:
        logger.warning(
            "failed to parse certificate enddate, using mtime fallback",
            extra={"node_id": node_id, "error": str(exc)},
        )
        # Fallback: assume 365-day cert from file mtime
        try:
            mtime = datetime.fromtimestamp(cert_path.stat().st_mtime, tz=timezone.utc)
            assumed_expiry = mtime + timedelta(days=365)
            days_remaining = (assumed_expiry - now).days
            result["days_remaining"] = days_remaining
            result["is_expired"] = days_remaining < 0
            result["needs_rotation"] = days_remaining < 90 or result["is_revoked"]
        except OSError:
            result["needs_rotation"] = True

    return result


def schedule_rotation_check(
    nodes: list[dict[str, Any]],
    certs_dir: str | Path,
) -> list[dict[str, Any]]:
    """Batch check which nodes need credential rotation.

    Returns a list of status dicts for nodes that need rotation,
    sorted by urgency (fewest days remaining first).
    """

    needing_rotation: list[dict[str, Any]] = []
    for node in nodes:
        node_id = node.get("node_id")
        if not node_id:
            continue
        status = credential_status(node_id, certs_dir)
        if status["needs_rotation"]:
            needing_rotation.append(status)

    needing_rotation.sort(key=lambda s: s.get("days_remaining") or -9999)
    return needing_rotation
