from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nexora_node_sdk.security_audit import append_security_event_to_file, build_security_event, summarize_security_events


class SecurityAuditTests(unittest.TestCase):
    def test_build_event_contains_category_and_action(self):
        """TASK-3-2-3-2: events are structured and timestamped."""

        event = build_security_event("tls", "handshake_failed", severity="warning", node_id="node-a")
        self.assertEqual(event["category"], "tls")
        self.assertEqual(event["action"], "handshake_failed")
        self.assertEqual(event["details"]["node_id"], "node-a")

    def test_append_security_event_to_file_persists_event(self):
        """TASK-3-15-3-1: events are append-only in state storage."""

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            append_security_event_to_file(path, build_security_event("auth", "token_issued"))
            self.assertIn("security_audit", path.read_text())

    def test_summarize_security_events_groups_categories(self):
        """TASK-3-2-3-2: summaries expose categories and severities."""

        summary = summarize_security_events([
            build_security_event("auth", "token_issued"),
            build_security_event("tls", "handshake_failed", severity="warning"),
        ])
        self.assertEqual(summary["total_events"], 2)
        self.assertEqual(summary["categories"]["auth"], 1)
        self.assertEqual(summary["severities"]["warning"], 1)


if __name__ == "__main__":
    unittest.main()
