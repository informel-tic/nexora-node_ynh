from __future__ import annotations

import unittest

from nexora_node_sdk.pra import build_backup_scope, build_restore_plan


class PRATests(unittest.TestCase):
    def test_build_backup_scope_keeps_selected_apps(self):
        scope = build_backup_scope("apps", include_apps=["nextcloud"])
        self.assertIn("nextcloud", scope["include_apps"])

    def test_build_restore_plan_contains_ordered_steps(self):
        plan = build_restore_plan("snap-1", target_node="node-a", offsite_source="s3://bucket")
        self.assertEqual(plan["steps"][0], "validate_snapshot")

    def test_build_restore_plan_keeps_offsite_source(self):
        plan = build_restore_plan("snap-1", target_node="node-a", offsite_source="nfs://backup")
        self.assertEqual(plan["offsite_source"], "nfs://backup")


if __name__ == "__main__":
    unittest.main()
