from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nexora_node_sdk.auth as auth


class AuthRuntimeResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_api_token = auth._token._api_token

    def tearDown(self) -> None:
        auth._token._api_token = self._original_api_token
        auth._AUTH_FAILURES.clear()

    def test_rate_limit_state_persists_across_memory_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_path = Path(tmp) / "auth-runtime.json"
            with patch.dict(os.environ, {"NEXORA_AUTH_RUNTIME_FILE": str(runtime_path)}, clear=False):
                auth._AUTH_FAILURES.clear()
                ip = "198.51.100.42"
                for _ in range(auth._MAX_AUTH_FAILURES):
                    auth._record_auth_failure(ip)

                # Simulate process restart by clearing in-memory state.
                auth._AUTH_FAILURES.clear()
                self.assertTrue(auth._check_rate_limit(ip))
                self.assertTrue(runtime_path.exists())

    def test_secret_store_replay_registry_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = auth.SecretStore(state_dir=tmp)
            issued = first.issue_scoped_secret("node", "node-replay", ["read_inventory"])
            first.consume_token(issued["token"])

            # New store instance should still detect replay from persisted registry.
            second = auth.SecretStore(state_dir=tmp)
            validation = second.validate_scoped_secret(issued["token"], "node")
            self.assertFalse(validation["valid"])
            self.assertIn("replay", validation["reasons"][0].lower())

    def test_rotate_api_token_updates_file_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "api-token"
            token_path.write_text("legacy-token", encoding="utf-8")
            with patch.dict(os.environ, {"NEXORA_API_TOKEN_FILE": str(token_path)}, clear=False):
                auth._token._api_token = None
                old_token = auth.get_api_token()
                self.assertEqual(old_token, "legacy-token")

                rotated = auth.rotate_api_token(reason="unit-test", token_file=token_path)
                self.assertTrue(rotated["rotated"])

                new_token = token_path.read_text(encoding="utf-8").strip()
                self.assertNotEqual(new_token, old_token)
                self.assertEqual(auth.get_api_token(), new_token)

                meta_path = token_path.with_name("api-token.meta.json")
                self.assertTrue(meta_path.exists())


if __name__ == "__main__":
    unittest.main()
