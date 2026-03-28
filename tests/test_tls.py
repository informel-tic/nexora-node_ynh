from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from nexora_node_sdk.tls import build_mtls_config, is_certificate_revoked, revoke_certificate


class TLSTests(unittest.TestCase):
    @unittest.mock.patch("nexora_node_sdk.tls.generate_node_credentials")
    def test_build_mtls_config_creates_ca_and_node_bundle(self, mock_gen):
        """TASK-3-2-1-2: a node can obtain a CA-backed mTLS bundle."""

        def mock_generate(node_id, fleet_id, certs_dir):
            c = Path(certs_dir) / f"{node_id}.crt"
            k = Path(certs_dir) / f"{node_id}.key"
            ca = Path(certs_dir) / "fleet-ca.crt"
            c.write_text("cert")
            k.write_text("key")
            ca.write_text("ca")
            return {"cert_path": str(c), "key_path": str(k)}
        
        mock_gen.side_effect = mock_generate

        with tempfile.TemporaryDirectory() as tmp:
            config = build_mtls_config("node-a", "fleet-1", tmp)
            self.assertEqual(config["cert"][0], str(Path(tmp) / "node-a.crt"))
            self.assertTrue(Path(config["verify"]).exists())
            self.assertTrue(Path(config["cert"][0]).exists())
            self.assertTrue(Path(config["cert"][1]).exists())

    def test_revoke_certificate_records_local_crl(self):
        """TASK-3-2-3-2: revocation is persisted in the local CRL."""

        with tempfile.TemporaryDirectory() as tmp:
            revoke_certificate(tmp, "node-b", reason="rotation")
            self.assertTrue(is_certificate_revoked(tmp, "node-b"))

    def test_unlisted_certificate_is_not_revoked(self):
        """TASK-3-2-3-2: CRL lookup is false for unknown nodes."""

        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(is_certificate_revoked(tmp, "node-c"))


if __name__ == "__main__":
    unittest.main()
