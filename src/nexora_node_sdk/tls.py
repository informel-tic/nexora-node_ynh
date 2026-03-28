"""TLS and mTLS helpers for Nexora fleet communication.

WS4-T03: Complete mTLS layer for remote operations — adds CRL timestamps,
certificate verification helpers, and a pre-flight check for remote calls.
"""

from __future__ import annotations

import json
import ssl
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .identity import generate_node_credentials


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_fleet_ca(certs_dir: str | Path, fleet_id: str) -> dict[str, str]:
    """Ensure the fleet CA exists by issuing a local node bundle if necessary."""

    certs_path = Path(certs_dir)
    generate_node_credentials("bootstrap-ca-check", fleet_id, certs_path)
    return {
        "ca_key": str(certs_path / "fleet-ca.key"),
        "ca_cert": str(certs_path / "fleet-ca.crt"),
    }


# TASK-3-2-1-2: mTLS with fleet CA.
def issue_node_certificate(
    node_id: str, fleet_id: str, certs_dir: str | Path
) -> dict[str, Any]:
    """Issue a CA-signed certificate bundle for a node."""

    ensure_fleet_ca(certs_dir, fleet_id)
    return generate_node_credentials(node_id, fleet_id, certs_dir)


# TASK-3-2-1-2: mTLS with fleet CA.
def build_mtls_config(
    node_id: str, fleet_id: str, certs_dir: str | Path
) -> dict[str, Any]:
    """Build client-side mTLS settings for remote fleet calls."""

    bundle = issue_node_certificate(node_id, fleet_id, certs_dir)
    ca = ensure_fleet_ca(certs_dir, fleet_id)
    return {
        "verify": ca["ca_cert"],
        "cert": (bundle["cert_path"], bundle["key_path"]),
        "https_only": True,
    }


# WS4-T03: Pre-flight mTLS verification for remote operations.
def verify_mtls_preconditions(
    node: dict[str, Any],
    *,
    certs_dir: str | Path,
) -> dict[str, Any]:
    """Check that a node's mTLS material is present and not revoked.

    Returns a dict with ``ready`` (bool) and a list of ``issues``.
    """
    node_id = str(node.get("node_id") or "")
    issues: list[str] = []

    cert_path = node.get("cert_path")
    key_path = node.get("key_path")

    if not cert_path or not Path(cert_path).exists():
        issues.append("missing_certificate")
    if not key_path or not Path(key_path).exists():
        issues.append("missing_private_key")
    if is_certificate_revoked(str(certs_dir), node_id):
        issues.append("certificate_revoked")

    ca_cert = Path(certs_dir) / "fleet-ca.crt"
    if not ca_cert.exists():
        issues.append("missing_fleet_ca")

    return {
        "node_id": node_id,
        "ready": len(issues) == 0,
        "issues": issues,
    }


# TASK-3-2-3-2: Security channel audit logging / CRL-like revocation.
def revoke_certificate(
    certs_dir: str | Path, node_id: str, *, reason: str
) -> dict[str, Any]:
    """Record a certificate revocation in a local JSON CRL with timestamp."""

    certs_path = Path(certs_dir)
    certs_path.mkdir(parents=True, exist_ok=True)
    crl_path = certs_path / "fleet-crl.json"
    payload = (
        json.loads(crl_path.read_text(encoding="utf-8"))
        if crl_path.exists()
        else {"revoked": []}
    )
    payload.setdefault("revoked", []).append(
        {
            "node_id": node_id,
            "reason": reason,
            "revoked_at": _utc_now_iso(),
        }
    )
    payload["updated_at"] = _utc_now_iso()
    crl_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload


def is_certificate_revoked(certs_dir: str | Path, node_id: str) -> bool:
    """Return whether a node is listed in the local CRL."""

    crl_path = Path(certs_dir) / "fleet-crl.json"
    if not crl_path.exists():
        return False
    payload = json.loads(crl_path.read_text(encoding="utf-8"))
    return any(entry.get("node_id") == node_id for entry in payload.get("revoked", []))


def list_revoked_certificates(certs_dir: str | Path) -> list[dict[str, Any]]:
    """Return the list of revoked certificates from the local CRL."""

    crl_path = Path(certs_dir) / "fleet-crl.json"
    if not crl_path.exists():
        return []
    payload = json.loads(crl_path.read_text(encoding="utf-8"))
    revoked = payload.get("revoked", [])
    return revoked if isinstance(revoked, list) else []


# ── WS4-T03: mTLS enforcement layer ─────────────────────────────────


def verify_client_certificate(
    cert_pem: str | bytes,
    fleet_id: str,
    certs_dir: str | Path,
) -> dict[str, Any]:
    """Validate a client certificate against the fleet CA and CRL.

    Performs:
    1. CA chain verification via OpenSSL
    2. Subject CN extraction
    3. CRL lookup for revocation
    4. Expiry date check

    Returns a dict with 'valid', 'node_id', 'subject', and 'reasons'.
    """

    certs_path = Path(certs_dir)
    ca_cert = certs_path / "fleet-ca.crt"
    reasons: list[str] = []

    if not ca_cert.exists():
        return {
            "valid": False,
            "node_id": None,
            "subject": None,
            "reasons": ["fleet CA certificate not found"],
        }

    # Write PEM to temp file for OpenSSL verification
    if isinstance(cert_pem, str):
        cert_pem = cert_pem.encode("utf-8")

    tmp_cert = certs_path / "_verify_tmp.pem"
    try:
        tmp_cert.write_bytes(cert_pem)

        # Verify chain
        proc = subprocess.run(
            ["openssl", "verify", "-CAfile", str(ca_cert), str(tmp_cert)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            reasons.append(
                f"certificate chain verification failed: {proc.stderr.strip()}"
            )
            return {
                "valid": False,
                "node_id": None,
                "subject": None,
                "reasons": reasons,
            }
        reasons.append("certificate chain verified against fleet CA")

        # Extract subject CN
        proc_subj = subprocess.run(
            ["openssl", "x509", "-in", str(tmp_cert), "-noout", "-subject"],
            capture_output=True,
            text=True,
            check=False,
        )
        subject_line = proc_subj.stdout.strip()
        node_id = None
        if "CN=" in subject_line or "CN =" in subject_line:
            # Handle both "CN = value" and "CN=value" formats
            cn_part = (
                subject_line.split("CN")[-1]
                .lstrip(" =")
                .split("/")[0]
                .split(",")[0]
                .strip()
            )
            node_id = cn_part
            reasons.append(f"extracted CN: {node_id}")

        # Check CRL
        if node_id and is_certificate_revoked(certs_dir, node_id):
            reasons.append("certificate is revoked in local CRL")
            return {
                "valid": False,
                "node_id": node_id,
                "subject": subject_line,
                "reasons": reasons,
            }
        reasons.append("certificate not found in revocation list")

        # Check expiry
        proc_dates = subprocess.run(
            ["openssl", "x509", "-in", str(tmp_cert), "-noout", "-enddate"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc_dates.returncode == 0:
            date_str = proc_dates.stdout.strip().split("=", 1)[-1]
            try:
                expires = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z").replace(
                    tzinfo=timezone.utc
                )
                now = datetime.now(timezone.utc)
                if expires < now:
                    reasons.append(f"certificate expired on {date_str}")
                    return {
                        "valid": False,
                        "node_id": node_id,
                        "subject": subject_line,
                        "reasons": reasons,
                    }
                reasons.append(f"certificate valid until {date_str}")
            except ValueError:
                reasons.append("could not parse certificate expiry date")

        return {
            "valid": True,
            "node_id": node_id,
            "subject": subject_line,
            "reasons": reasons,
        }
    finally:
        tmp_cert.unlink(missing_ok=True)


def build_server_tls_context(
    fleet_id: str,
    certs_dir: str | Path,
) -> ssl.SSLContext:
    """Build an ssl.SSLContext for a server requiring client certificates.

    The context:
    - Uses TLS 1.2+ only
    - Loads the fleet CA as the trusted client CA
    - Loads the server certificate (control-plane.<fleet_id>)
    - Requires and verifies client certificates
    """

    certs_path = Path(certs_dir)
    ca_cert = certs_path / "fleet-ca.crt"
    server_cert = certs_path / "control-plane.crt"
    server_key = certs_path / "control-plane.key"

    # Generate server cert if missing
    if not server_cert.exists():
        generate_node_credentials("control-plane", fleet_id, certs_path)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(certfile=str(server_cert), keyfile=str(server_key))
    ctx.load_verify_locations(cafile=str(ca_cert))
    return ctx


def build_client_tls_context(
    node_id: str,
    fleet_id: str,
    certs_dir: str | Path,
) -> ssl.SSLContext:
    """Build an ssl.SSLContext for a client connecting to a mTLS server.

    The context:
    - Uses TLS 1.2+ only
    - Loads the node certificate and key
    - Trusts the fleet CA for server verification
    """

    certs_path = Path(certs_dir)
    ca_cert = certs_path / "fleet-ca.crt"
    node_cert = certs_path / f"{node_id}.crt"
    node_key = certs_path / f"{node_id}.key"

    # Generate node cert if missing
    if not node_cert.exists():
        generate_node_credentials(node_id, fleet_id, certs_path)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(node_cert), keyfile=str(node_key))
    ctx.load_verify_locations(cafile=str(ca_cert))
    return ctx
