from __future__ import annotations

import unittest

from nexora_node_sdk.capabilities import capability_catalog_payload, list_capabilities, summarize_capabilities


class CapabilityCatalogTests(unittest.TestCase):
    def test_capability_catalog_contains_entries(self):
        capabilities = list_capabilities()
        self.assertGreaterEqual(len(capabilities), 5)
        capability_ids = {entry.get("id") for entry in capabilities if isinstance(entry, dict)}
        self.assertIn("fleet.enrollment", capability_ids)
        self.assertIn("node.actions", capability_ids)

    def test_capability_summary_counts_statuses(self):
        summary = summarize_capabilities()
        self.assertGreaterEqual(summary["total"], 5)
        self.assertIn("implemented", summary["by_status"])
        self.assertIn("partial", summary["by_status"])

    def test_capability_payload_contains_summary_and_capabilities(self):
        payload = capability_catalog_payload()
        self.assertIn("summary", payload)
        self.assertIn("capabilities", payload)
        self.assertEqual(payload["summary"]["total"], len(payload["capabilities"]))


if __name__ == "__main__":
    unittest.main()
