from __future__ import annotations

import unittest

from nexora_node_sdk.security_audit import build_security_event


class SecurityHardeningTests(unittest.TestCase):
    def test_machine_and_human_events_are_distinguishable(self):
        """TASK-3-15-1-1: security events distinguish actor roles."""

        event = build_security_event("auth", "token_issued", actor_role="machine", scope="rotate_credentials")
        self.assertEqual(event["details"]["actor_role"], "machine")

    def test_secrets_are_never_embedded_in_event_payload(self):
        """TASK-3-15-2-1: secret material is omitted from audit payloads."""

        event = build_security_event("auth", "token_rotated", secret_ref="node-a-token")
        self.assertIn("secret_ref", event["details"])
        self.assertNotIn("secret", {k for k in event["details"] if k == "secret"})

    def test_high_severity_audit_event_is_reported(self):
        """TASK-3-15-3-1: high severity events retain their classification."""

        event = build_security_event("tls", "handshake_refused", severity="critical")
        self.assertEqual(event["severity"], "critical")


if __name__ == "__main__":
    unittest.main()
