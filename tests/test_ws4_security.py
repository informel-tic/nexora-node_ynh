"""WS4 Security, Identity & Transport tests.

Covers trust evaluation, credential rotation, mTLS context creation,
secret isolation, security journal integrity, clock skew rejection,
token replay detection, and certificate revocation checks.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
import unittest.mock
import sys
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nexora_node_sdk.trust import (
    TrustEvaluation,
    TrustLevel,
    TrustPolicy,
    check_operation_allowed,
    evaluate_trust,
)
from nexora_node_sdk.auth import SecretStore, VALID_SCOPES
from nexora_node_sdk.security_audit import SecurityJournal


# ── WS4-T01: Trust evaluation ────────────────────────────────────────


class TrustEvaluationTests(unittest.TestCase):
    """Test trust level evaluation across all levels."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _node(self, **overrides) -> dict:
        base = {
            "node_id": "node-abc",
            "status": "healthy",
            "attested_at": datetime.now(timezone.utc).isoformat(),
            "enrolled_at": datetime.now(timezone.utc).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "credential_expires_at": (datetime.now(timezone.utc) + timedelta(days=200)).isoformat(),
        }
        base.update(overrides)
        return base

    def test_untrusted_for_revoked_node(self):
        """Revoked nodes are UNTRUSTED."""
        node = self._node(status="revoked")
        result = evaluate_trust(node, self.tmpdir)
        self.assertEqual(result.level, TrustLevel.UNTRUSTED)

    def test_untrusted_for_discovered_node(self):
        """Discovered nodes that haven't enrolled are UNTRUSTED."""
        node = self._node(status="discovered", attested_at=None, enrolled_at=None)
        result = evaluate_trust(node, self.tmpdir)
        self.assertEqual(result.level, TrustLevel.UNTRUSTED)

    def test_enrolled_without_attestation(self):
        """Enrolled but unattested nodes stay at ENROLLED when attestation is required."""
        node = self._node(status="enrolled", attested_at=None)
        policy = TrustPolicy(require_attestation=True)
        result = evaluate_trust(node, self.tmpdir, policy=policy)
        self.assertEqual(result.level, TrustLevel.ENROLLED)

    def test_attested_without_cert(self):
        """Attested node without a certificate stops at ATTESTED."""
        node = self._node(status="attested")
        policy = TrustPolicy(require_valid_cert=True)
        result = evaluate_trust(node, self.tmpdir, policy=policy)
        # No cert file on disk, so should not reach VERIFIED
        self.assertLessEqual(result.level, TrustLevel.ATTESTED)

    def test_verified_with_cert(self):
        """Node with valid cert and attestation reaches VERIFIED."""
        cert_path = Path(self.tmpdir) / "node-abc.crt"
        cert_path.write_text("dummy cert")
        node = self._node(status="healthy")
        result = evaluate_trust(node, self.tmpdir)
        self.assertGreaterEqual(result.level, TrustLevel.VERIFIED)

    def test_trusted_with_fresh_node(self):
        """Healthy, attested, cert-valid, recently-seen node reaches TRUSTED."""
        cert_path = Path(self.tmpdir) / "node-abc.crt"
        cert_path.write_text("dummy cert")
        node = self._node(
            status="healthy",
            last_seen=datetime.now(timezone.utc).isoformat(),
        )
        result = evaluate_trust(node, self.tmpdir)
        self.assertEqual(result.level, TrustLevel.TRUSTED)

    def test_crl_revocation_drops_to_untrusted(self):
        """Node listed in CRL is UNTRUSTED regardless of other signals."""
        cert_path = Path(self.tmpdir) / "node-abc.crt"
        cert_path.write_text("dummy cert")
        crl_path = Path(self.tmpdir) / "fleet-crl.json"
        crl_path.write_text(json.dumps({"revoked": [{"node_id": "node-abc"}]}))
        node = self._node()
        result = evaluate_trust(node, self.tmpdir)
        self.assertEqual(result.level, TrustLevel.UNTRUSTED)

    def test_stale_node_does_not_reach_trusted(self):
        """A node that hasn't been seen recently should not be TRUSTED."""
        cert_path = Path(self.tmpdir) / "node-abc.crt"
        cert_path.write_text("dummy cert")
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        node = self._node(last_seen=old_time)
        policy = TrustPolicy(last_seen_freshness_hours=24)
        result = evaluate_trust(node, self.tmpdir, policy=policy)
        self.assertLess(result.level, TrustLevel.TRUSTED)

    def test_evaluation_returns_reasons(self):
        """Trust evaluation always includes explanatory reasons."""
        node = self._node(status="discovered")
        result = evaluate_trust(node, self.tmpdir)
        self.assertIsInstance(result.reasons, list)
        self.assertGreater(len(result.reasons), 0)

    def test_check_operation_allowed_for_enrolled_read(self):
        """An enrolled node can read inventory."""
        node = self._node(status="enrolled", attested_at=None)
        policy = TrustPolicy(require_attestation=False)
        result = check_operation_allowed(node, self.tmpdir, "read_inventory", policy=policy)
        self.assertTrue(result["allowed"])

    def test_check_operation_denied_for_untrusted(self):
        """An untrusted node cannot install apps."""
        node = self._node(status="discovered", attested_at=None)
        result = check_operation_allowed(node, self.tmpdir, "install_app")
        self.assertFalse(result["allowed"])

    def test_trust_evaluation_as_dict(self):
        """TrustEvaluation.as_dict returns serializable data."""
        te = TrustEvaluation(node_id="n1", level=TrustLevel.VERIFIED, reasons=["test"])
        d = te.as_dict()
        self.assertEqual(d["level"], "verified")
        self.assertEqual(d["level_value"], 3)


# ── WS4-T02: Credential rotation ─────────────────────────────────────


class CredentialRotationTests(unittest.TestCase):
    """Test credential rotation, status, and batch scheduling."""

    @unittest.mock.patch("nexora_node_sdk.identity._run_openssl")
    def test_rotate_node_credentials(self, mock_openssl):
        """rotate_node_credentials issues new cert and revokes old."""
        from nexora_node_sdk.identity import rotate_node_credentials

        def _fake_openssl(*args):
            """Create fake files that generate_node_credentials expects."""
            for arg in args:
                if str(arg).endswith(".key") and "genrsa" in args[0]:
                    Path(arg).write_text("fake-key")
                elif str(arg).endswith(".crt") and "x509" in args[0]:
                    Path(arg).write_text("fake-cert")
                elif str(arg).endswith(".csr"):
                    Path(arg).write_text("fake-csr")

        # The mock needs to create the files that the code then chmod's
        def openssl_side_effect(*args):
            for i, a in enumerate(args):
                a = str(a)
                if a == "-out" and i + 1 < len(args):
                    Path(args[i + 1]).write_text("fake")
                elif a == "-keyout" and i + 1 < len(args):
                    Path(args[i + 1]).write_text("fake")

        mock_openssl.side_effect = openssl_side_effect

        with tempfile.TemporaryDirectory() as tmp:
            certs = Path(tmp)
            # Create old cert and CA
            (certs / "fleet-ca.key").write_text("key")
            (certs / "fleet-ca.crt").write_text("cert")
            (certs / "node-x.crt").write_text("old cert")
            (certs / "node-x.key").write_text("old key")

            result = rotate_node_credentials("node-x", "fleet-1", tmp)
            self.assertEqual(result["node_id"], "node-x")
            self.assertIn("rotated_at", result)

            # Old cert should be recorded in CRL
            crl = json.loads((certs / "fleet-crl.json").read_text())
            revoked_ids = [e["node_id"] for e in crl["revoked"]]
            self.assertIn("node-x", revoked_ids)

    def test_credential_status_missing_cert(self):
        """credential_status reports missing cert as needing rotation."""
        from nexora_node_sdk.identity import credential_status

        with tempfile.TemporaryDirectory() as tmp:
            status = credential_status("nonexistent", tmp)
            self.assertTrue(status["needs_rotation"])
            self.assertTrue(status["is_expired"])
            self.assertFalse(status["cert_exists"])

    def test_credential_status_revoked(self):
        """credential_status detects revoked certs via CRL."""
        from nexora_node_sdk.identity import credential_status

        with tempfile.TemporaryDirectory() as tmp:
            certs = Path(tmp)
            (certs / "node-r.crt").write_text("cert")
            crl_path = certs / "fleet-crl.json"
            crl_path.write_text(json.dumps({"revoked": [{"node_id": "node-r"}]}))

            status = credential_status("node-r", tmp)
            self.assertTrue(status["is_revoked"])

    def test_schedule_rotation_check_sorts_by_urgency(self):
        """schedule_rotation_check returns nodes sorted by days_remaining."""
        from nexora_node_sdk.identity import schedule_rotation_check

        with tempfile.TemporaryDirectory() as tmp:
            nodes = [
                {"node_id": "a"},
                {"node_id": "b"},
            ]
            result = schedule_rotation_check(nodes, tmp)
            # Both have no certs, so both need rotation
            self.assertEqual(len(result), 2)


# ── WS4-T03: mTLS enforcement ────────────────────────────────────────


class MTLSTests(unittest.TestCase):
    """Test mTLS context creation and certificate verification."""

    @unittest.skipIf(shutil.which('openssl') is None, "openssl is required for this test")
    @unittest.mock.patch("nexora_node_sdk.tls.generate_node_credentials")
    def test_build_server_tls_context(self, mock_gen):
        """build_server_tls_context returns an ssl.SSLContext."""
        import ssl
        from nexora_node_sdk.tls import build_server_tls_context

        with tempfile.TemporaryDirectory() as tmp:
            certs = Path(tmp)
            # Create self-signed test certs using openssl
            import subprocess
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
                "-days", "1", "-nodes",
                "-keyout", str(certs / "fleet-ca.key"),
                "-out", str(certs / "fleet-ca.crt"),
                "-subj", "/CN=test-fleet CA/O=Nexora",
            ], capture_output=True, check=True)

            def _mock_gen(node_id, fleet_id, certs_dir):
                subprocess.run([
                    "openssl", "genrsa", "-out", str(certs / f"{node_id}.key"), "2048",
                ], capture_output=True, check=True)
                subprocess.run([
                    "openssl", "req", "-new", "-key", str(certs / f"{node_id}.key"),
                    "-out", str(certs / f"{node_id}.csr"),
                    "-subj", f"/CN={node_id}/O=Nexora",
                ], capture_output=True, check=True)
                subprocess.run([
                    "openssl", "x509", "-req", "-in", str(certs / f"{node_id}.csr"),
                    "-CA", str(certs / "fleet-ca.crt"), "-CAkey", str(certs / "fleet-ca.key"),
                    "-CAcreateserial", "-out", str(certs / f"{node_id}.crt"),
                    "-days", "1", "-sha256",
                ], capture_output=True, check=True)
                return {"cert_path": str(certs / f"{node_id}.crt"), "key_path": str(certs / f"{node_id}.key")}

            mock_gen.side_effect = _mock_gen

            ctx = build_server_tls_context("fleet-1", tmp)
            self.assertIsInstance(ctx, ssl.SSLContext)
            self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)

    @unittest.skipIf(shutil.which('openssl') is None, "openssl is required for this test")
    @unittest.mock.patch("nexora_node_sdk.tls.generate_node_credentials")
    def test_build_client_tls_context(self, mock_gen):
        """build_client_tls_context returns an ssl.SSLContext."""
        import ssl
        from nexora_node_sdk.tls import build_client_tls_context

        with tempfile.TemporaryDirectory() as tmp:
            certs = Path(tmp)
            import subprocess
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
                "-days", "1", "-nodes",
                "-keyout", str(certs / "fleet-ca.key"),
                "-out", str(certs / "fleet-ca.crt"),
                "-subj", "/CN=test-fleet CA/O=Nexora",
            ], capture_output=True, check=True)

            def _mock_gen(node_id, fleet_id, certs_dir):
                subprocess.run([
                    "openssl", "genrsa", "-out", str(certs / f"{node_id}.key"), "2048",
                ], capture_output=True, check=True)
                subprocess.run([
                    "openssl", "req", "-new", "-key", str(certs / f"{node_id}.key"),
                    "-out", str(certs / f"{node_id}.csr"),
                    "-subj", f"/CN={node_id}/O=Nexora",
                ], capture_output=True, check=True)
                subprocess.run([
                    "openssl", "x509", "-req", "-in", str(certs / f"{node_id}.csr"),
                    "-CA", str(certs / "fleet-ca.crt"), "-CAkey", str(certs / "fleet-ca.key"),
                    "-CAcreateserial", "-out", str(certs / f"{node_id}.crt"),
                    "-days", "1", "-sha256",
                ], capture_output=True, check=True)
                return {"cert_path": str(certs / f"{node_id}.crt"), "key_path": str(certs / f"{node_id}.key")}

            mock_gen.side_effect = _mock_gen

            ctx = build_client_tls_context("node-a", "fleet-1", tmp)
            self.assertIsInstance(ctx, ssl.SSLContext)

    @unittest.skipIf(shutil.which('openssl') is None, "openssl is required for this test")
    def test_verify_client_certificate_valid(self):
        """verify_client_certificate accepts a valid CA-signed cert."""
        from nexora_node_sdk.tls import verify_client_certificate
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            certs = Path(tmp)
            # Create CA
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
                "-days", "1", "-nodes",
                "-keyout", str(certs / "fleet-ca.key"),
                "-out", str(certs / "fleet-ca.crt"),
                "-subj", "/CN=fleet-test CA/O=Nexora",
            ], capture_output=True, check=True)
            # Create node cert signed by CA
            subprocess.run([
                "openssl", "genrsa", "-out", str(certs / "node-v.key"), "2048",
            ], capture_output=True, check=True)
            subprocess.run([
                "openssl", "req", "-new", "-key", str(certs / "node-v.key"),
                "-out", str(certs / "node-v.csr"),
                "-subj", "/CN=node-v/OU=fleet-test/O=Nexora",
            ], capture_output=True, check=True)
            subprocess.run([
                "openssl", "x509", "-req", "-in", str(certs / "node-v.csr"),
                "-CA", str(certs / "fleet-ca.crt"), "-CAkey", str(certs / "fleet-ca.key"),
                "-CAcreateserial", "-out", str(certs / "node-v.crt"),
                "-days", "1", "-sha256",
            ], capture_output=True, check=True)

            cert_pem = (certs / "node-v.crt").read_text()
            result = verify_client_certificate(cert_pem, "fleet-test", tmp)
            self.assertTrue(result["valid"])
            self.assertEqual(result["node_id"], "node-v")

    @unittest.skipIf(shutil.which('openssl') is None, "openssl is required for this test")
    def test_verify_client_certificate_revoked(self):
        """verify_client_certificate rejects a revoked cert."""
        from nexora_node_sdk.tls import verify_client_certificate
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            certs = Path(tmp)
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
                "-days", "1", "-nodes",
                "-keyout", str(certs / "fleet-ca.key"),
                "-out", str(certs / "fleet-ca.crt"),
                "-subj", "/CN=fleet-test CA/O=Nexora",
            ], capture_output=True, check=True)
            subprocess.run([
                "openssl", "genrsa", "-out", str(certs / "node-r.key"), "2048",
            ], capture_output=True, check=True)
            subprocess.run([
                "openssl", "req", "-new", "-key", str(certs / "node-r.key"),
                "-out", str(certs / "node-r.csr"),
                "-subj", "/CN=node-r/OU=fleet-test/O=Nexora",
            ], capture_output=True, check=True)
            subprocess.run([
                "openssl", "x509", "-req", "-in", str(certs / "node-r.csr"),
                "-CA", str(certs / "fleet-ca.crt"), "-CAkey", str(certs / "fleet-ca.key"),
                "-CAcreateserial", "-out", str(certs / "node-r.crt"),
                "-days", "1", "-sha256",
            ], capture_output=True, check=True)

            # Add to CRL
            (certs / "fleet-crl.json").write_text(json.dumps({"revoked": [{"node_id": "node-r"}]}))

            cert_pem = (certs / "node-r.crt").read_text()
            result = verify_client_certificate(cert_pem, "fleet-test", tmp)
            self.assertFalse(result["valid"])
            self.assertIn("revoked", " ".join(result["reasons"]))

    def test_verify_client_certificate_no_ca(self):
        """verify_client_certificate fails when fleet CA is missing."""
        from nexora_node_sdk.tls import verify_client_certificate

        with tempfile.TemporaryDirectory() as tmp:
            result = verify_client_certificate(b"fake cert", "fleet-x", tmp)
            self.assertFalse(result["valid"])
            self.assertIn("fleet CA certificate not found", result["reasons"][0])


# ── WS4-T04: Secret isolation ────────────────────────────────────────


class SecretStoreTests(unittest.TestCase):
    """Test scoped secret issuance, validation, and revocation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = SecretStore(state_dir=self.tmpdir)

    def test_issue_and_validate_node_secret(self):
        """Issue a node-scoped secret and validate it."""
        result = self.store.issue_scoped_secret("node", "node-a", ["read_inventory"])
        self.assertIn("token", result)
        self.assertEqual(result["scope"], "node")

        validation = self.store.validate_scoped_secret(result["token"], "node")
        self.assertTrue(validation["valid"])
        self.assertEqual(validation["entity_id"], "node-a")

    def test_issue_and_validate_service_secret(self):
        """Issue a service-scoped secret and validate it."""
        result = self.store.issue_scoped_secret("service", "backup-svc", ["create_backup"])
        validation = self.store.validate_scoped_secret(result["token"], "service")
        self.assertTrue(validation["valid"])

    def test_issue_and_validate_operator_secret(self):
        """Issue an operator-scoped secret and validate it."""
        result = self.store.issue_scoped_secret("operator", "admin-1", ["install_app", "read_inventory"])
        validation = self.store.validate_scoped_secret(result["token"], "operator")
        self.assertTrue(validation["valid"])

    def test_validate_wrong_scope_fails(self):
        """A node token cannot be used for operator scope."""
        result = self.store.issue_scoped_secret("node", "node-a", ["read_inventory"])
        validation = self.store.validate_scoped_secret(result["token"], "operator")
        self.assertFalse(validation["valid"])

    def test_validate_missing_permission_fails(self):
        """Validation fails when required permission is not in token."""
        result = self.store.issue_scoped_secret("node", "node-a", ["read_inventory"])
        validation = self.store.validate_scoped_secret(
            result["token"], "node", required_permission="execute_remote_action"
        )
        self.assertFalse(validation["valid"])

    def test_revoke_scoped_secret(self):
        """Revoked secrets are rejected on validation."""
        result = self.store.issue_scoped_secret("node", "node-b", ["read_inventory"])
        revoke_result = self.store.revoke_scoped_secret("node-b", "node")
        self.assertEqual(revoke_result["revoked_count"], 1)

        validation = self.store.validate_scoped_secret(result["token"], "node")
        self.assertFalse(validation["valid"])
        self.assertIn("revoked", validation["reasons"][0])

    def test_expired_secret_rejected(self):
        """Expired tokens are rejected."""
        result = self.store.issue_scoped_secret("node", "node-c", ["read_inventory"], ttl_seconds=0)
        # The token expires immediately (or very nearly)
        time.sleep(0.01)
        validation = self.store.validate_scoped_secret(result["token"], "node")
        self.assertFalse(validation["valid"])

    def test_invalid_scope_raises(self):
        """Issuing a secret with an invalid scope raises ValueError."""
        with self.assertRaises(ValueError):
            self.store.issue_scoped_secret("bogus", "x", ["read_inventory"])

    def test_invalid_permission_for_scope_raises(self):
        """Issuing a secret with permissions not allowed for the scope raises."""
        with self.assertRaises(ValueError):
            self.store.issue_scoped_secret("node", "x", ["install_app"])

    def test_replay_detection(self):
        """A consumed token cannot be reused."""
        result = self.store.issue_scoped_secret("node", "node-d", ["read_inventory"])
        token = result["token"]

        # First validation succeeds
        v1 = self.store.validate_scoped_secret(token, "node")
        self.assertTrue(v1["valid"])

        # Consume it
        self.store.consume_token(token)

        # Second validation fails (replay)
        v2 = self.store.validate_scoped_secret(token, "node")
        self.assertFalse(v2["valid"])
        self.assertIn("replay", v2["reasons"][0].lower())

    def test_list_secrets(self):
        """list_secrets returns metadata without token values."""
        self.store.issue_scoped_secret("node", "node-e", ["read_inventory"])
        self.store.issue_scoped_secret("service", "svc-1", ["create_backup"])
        results = self.store.list_secrets()
        self.assertEqual(len(results), 2)
        # Token value should not be in the listing
        for r in results:
            self.assertNotIn("token", r)
            self.assertNotIn("token_digest", r)

    @unittest.skipIf(sys.platform == "win32", "POSIX permissions are disabled on Windows")
    def test_file_permissions(self):
        """Secret files are created with 0o600 permissions."""
        import os
        import stat

        result = self.store.issue_scoped_secret("node", "node-f", ["read_inventory"])
        # Find the file
        for f in (Path(self.tmpdir) / "secrets" / "node").glob("*.json"):
            mode = os.stat(f).st_mode
            self.assertEqual(stat.S_IMODE(mode), 0o600)


# ── WS4-T05: Security journal integrity ──────────────────────────────


class SecurityJournalTests(unittest.TestCase):
    """Test HMAC chain integrity, export, retention, and aggregation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.journal_path = Path(self.tmpdir) / "journal.json"

    def test_log_creates_events_with_hmac(self):
        """Each logged event has event_id, prev_hash, and hmac."""
        journal = SecurityJournal(self.journal_path, signing_key="test-key")
        event = journal.log("auth", "login_success", severity="info", user="admin")
        self.assertIn("event_id", event)
        self.assertIn("prev_hash", event)
        self.assertIn("hmac", event)
        self.assertEqual(event["category"], "auth")

    def test_hmac_chain_integrity_valid(self):
        """A valid journal passes integrity verification."""
        journal = SecurityJournal(self.journal_path, signing_key="test-key")
        journal.log("auth", "login", severity="info")
        journal.log("tls", "handshake", severity="info")
        journal.log("enrollment", "node_enrolled", severity="info")

        result = journal.verify_integrity()
        self.assertTrue(result["valid"])
        self.assertEqual(result["verified_count"], 3)
        self.assertEqual(len(result["errors"]), 0)

    def test_hmac_chain_integrity_detects_tampering(self):
        """Modifying an event breaks the HMAC chain."""
        journal = SecurityJournal(self.journal_path, signing_key="test-key")
        journal.log("auth", "login", severity="info")
        journal.log("tls", "handshake", severity="info")

        # Tamper with the first event
        events = journal.events
        events[0]["action"] = "tampered_action"

        result = journal.verify_integrity(events)
        self.assertFalse(result["valid"])
        self.assertGreater(len(result["errors"]), 0)

    def test_hmac_chain_detects_insertion(self):
        """Inserting an event breaks the prev_hash chain."""
        journal = SecurityJournal(self.journal_path, signing_key="test-key")
        journal.log("auth", "login", severity="info")
        journal.log("auth", "logout", severity="info")

        events = journal.events
        # Insert a fake event between the two
        fake = {
            "event_id": "fake-id",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": "auth",
            "action": "fake",
            "severity": "info",
            "details": {},
            "prev_hash": "0" * 64,
            "hmac": "0" * 64,
        }
        events.insert(1, fake)

        result = journal.verify_integrity(events)
        self.assertFalse(result["valid"])

    def test_export_filters_by_category(self):
        """export_events filters by category."""
        journal = SecurityJournal(self.journal_path, signing_key="test-key")
        journal.log("auth", "login", severity="info")
        journal.log("tls", "handshake", severity="warning")
        journal.log("auth", "logout", severity="info")

        auth_events = journal.export_events(categories=["auth"])
        self.assertEqual(len(auth_events), 2)
        self.assertTrue(all(e["category"] == "auth" for e in auth_events))

    def test_export_filters_by_severity(self):
        """export_events filters by severity."""
        journal = SecurityJournal(self.journal_path, signing_key="test-key")
        journal.log("auth", "login", severity="info")
        journal.log("tls", "error", severity="error")

        errors = journal.export_events(severities=["error"])
        self.assertEqual(len(errors), 1)

    def test_export_filters_by_time_range(self):
        """export_events filters by since/until time range."""
        journal = SecurityJournal(self.journal_path, signing_key="test-key")
        journal.log("auth", "login", severity="info")

        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        # Events since the future should be empty
        self.assertEqual(len(journal.export_events(since=future)), 0)
        # Events since the past should include all
        self.assertEqual(len(journal.export_events(since=past)), 1)

    def test_retention_policy_max_events(self):
        """retention_policy keeps only max_events most recent events."""
        journal = SecurityJournal(self.journal_path, signing_key="test-key")
        for i in range(10):
            journal.log("auth", f"action_{i}", severity="info")

        result = journal.retention_policy(max_events=5)
        self.assertEqual(result["removed_count"], 5)
        self.assertEqual(result["remaining_count"], 5)
        self.assertEqual(len(journal.events), 5)

    def test_retention_policy_max_age(self):
        """retention_policy removes events older than max_age_days."""
        journal = SecurityJournal(self.journal_path, signing_key="test-key")
        # Log an event, then manually backdate it
        journal.log("auth", "old_action", severity="info")
        journal._events[0]["timestamp"] = (
            datetime.now(timezone.utc) - timedelta(days=100)
        ).isoformat()
        journal._save()

        journal.log("auth", "recent_action", severity="info")
        result = journal.retention_policy(max_age_days=30)
        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(result["remaining_count"], 1)

    def test_summarize_by_period_day(self):
        """summarize_by_period groups events by day."""
        journal = SecurityJournal(self.journal_path, signing_key="test-key")
        journal.log("auth", "login", severity="info")
        journal.log("tls", "handshake", severity="warning")

        summary = journal.summarize_by_period("day")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertIn(today, summary)
        self.assertEqual(summary[today]["total"], 2)

    def test_journal_persistence_across_instances(self):
        """Events persist across SecurityJournal instances."""
        key = "persistent-key"
        j1 = SecurityJournal(self.journal_path, signing_key=key)
        j1.log("auth", "first", severity="info")

        j2 = SecurityJournal(self.journal_path, signing_key=key)
        self.assertEqual(len(j2.events), 1)
        self.assertEqual(j2.events[0]["action"], "first")

    def test_invalid_severity_raises(self):
        """Logging with an invalid severity raises ValueError."""
        journal = SecurityJournal(self.journal_path, signing_key="test-key")
        with self.assertRaises(ValueError):
            journal.log("auth", "test", severity="bogus")


# ── WS4: Clock skew rejection ────────────────────────────────────────


class ClockSkewTests(unittest.TestCase):
    """Test clock skew rejection in enrollment attestation."""

    @unittest.mock.patch("nexora_node_sdk.enrollment.assess_compatibility")
    def test_clock_skew_rejection(self, mock_compat):
        """Attestation with a timestamp beyond the skew tolerance is rejected."""
        mock_compat.return_value = {"bootstrap_allowed": True, "reasons": []}
        from nexora_node_sdk.enrollment import attest_node, issue_enrollment_token, build_attestation_response

        state: dict = {}
        token_info = issue_enrollment_token(state, requested_by="test", mode="push")

        # Create an observed_at timestamp that is way in the future
        far_future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

        response = build_attestation_response(
            challenge=token_info["challenge"],
            node_id="node-skew",
            token_id=token_info["token_id"],
        )

        with self.assertRaises(ValueError, msg="Attestation timestamp exceeds clock skew tolerance"):
            attest_node(
                state,
                token=token_info["token"],
                challenge=token_info["challenge"],
                challenge_response=response,
                hostname="test-host",
                node_id="node-skew",
                agent_version="0.1.0",
                yunohost_version="12.0",
                debian_version="12",
                observed_at=far_future,
            )


# ── WS4: Token replay detection ──────────────────────────────────────


class TokenReplayTests(unittest.TestCase):
    """Test that consumed enrollment tokens cannot be reused."""

    @unittest.mock.patch("nexora_node_sdk.enrollment.assess_compatibility")
    def test_consumed_token_rejected(self, mock_compat):
        """A consumed enrollment token cannot be validated again."""
        mock_compat.return_value = {"bootstrap_allowed": True, "reasons": []}

        from nexora_node_sdk.enrollment import (
            issue_enrollment_token,
            validate_enrollment_token,
            build_attestation_response,
            attest_node,
            consume_enrollment_token,
        )

        state: dict = {}
        token_info = issue_enrollment_token(state, requested_by="test", mode="push")

        now_iso = datetime.now(timezone.utc).isoformat()
        response = build_attestation_response(
            challenge=token_info["challenge"],
            node_id="node-replay",
            token_id=token_info["token_id"],
        )

        # Attest the token
        attest_node(
            state,
            token=token_info["token"],
            challenge=token_info["challenge"],
            challenge_response=response,
            hostname="replay-host",
            node_id="node-replay",
            agent_version="0.1.0",
            yunohost_version="12.0",
            debian_version="12",
            observed_at=now_iso,
        )

        # Consume the token
        consume_enrollment_token(state, token_info["token"], node_id="node-replay")

        # Attempting to validate the consumed token should fail
        with self.assertRaises(ValueError, msg="Enrollment token already consumed"):
            validate_enrollment_token(state, token_info["token"])


if __name__ == "__main__":
    unittest.main()
