from __future__ import annotations

import unittest

from nexora_node_sdk.sync import build_sync_plan
from nexora_node_sdk.sync_engine import execute_sync_plan, rollback_sync_execution


class SyncEngineTests(unittest.TestCase):
    def test_execute_sync_plan_supports_dry_run(self):
        plan = build_sync_plan({"node_id": "ref", "inventory": {}}, [{"node_id": "t1", "inventory": {}}], "branding")
        result = execute_sync_plan(plan, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["targets"][0]["actions"][0]["status"], "planned")

    def test_execute_sync_plan_can_apply(self):
        plan = build_sync_plan({"node_id": "ref", "inventory": {}}, [{"node_id": "t1", "inventory": {}}], "branding")
        result = execute_sync_plan(plan, dry_run=False)
        self.assertEqual(result["targets"][0]["actions"][0]["status"], "applied")

    def test_rollback_sync_execution_reports_reverted_actions(self):
        execution = {"targets": [{"target_node": "t1", "actions": [{}, {}]}]}
        rollback = rollback_sync_execution(execution)
        self.assertTrue(rollback["rolled_back"])
        self.assertEqual(rollback["targets"][0]["reverted_actions"], 2)


if __name__ == "__main__":
    unittest.main()
