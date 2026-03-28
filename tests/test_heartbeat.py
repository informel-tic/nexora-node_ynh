from __future__ import annotations

import unittest

from nexora_node_sdk.heartbeat import create_heartbeat, record_heartbeat, summarize_heartbeat_state


class HeartbeatTests(unittest.TestCase):
    def test_create_heartbeat_is_versioned(self):
        payload = create_heartbeat("node-a", status="healthy", roles=["apps"])
        self.assertEqual(payload["inventory_version"], "1.0")

    def test_record_heartbeat_updates_state(self):
        state = {"heartbeats": [], "inventory_snapshots": []}
        record_heartbeat(state, create_heartbeat("node-a", status="healthy", roles=["apps"]))
        self.assertEqual(len(state["heartbeats"]), 1)
        self.assertEqual(state["inventory_snapshots"][0]["kind"], "heartbeat")

    def test_summarize_heartbeat_state_tracks_latest_nodes(self):
        report = summarize_heartbeat_state([
            create_heartbeat("node-a", status="healthy", roles=["apps"]),
            create_heartbeat("node-b", status="healthy", roles=["mail"]),
        ])
        self.assertEqual(report["total_nodes"], 2)


if __name__ == "__main__":
    unittest.main()
