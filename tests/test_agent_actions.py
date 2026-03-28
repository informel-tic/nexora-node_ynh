from __future__ import annotations

import unittest
from pathlib import Path

from nexora_node_sdk.operator_actions import list_supported_agent_actions, summarize_agent_capabilities


class AgentActionsTests(unittest.TestCase):
    def test_supported_agent_actions_cover_expected_endpoints(self):
        """TASK-3-3-1-1: the action catalog exposes the required remote operations."""

        actions = list_supported_agent_actions()
        self.assertIn("branding/apply", actions)
        self.assertIn("healthcheck/run", actions)
        self.assertIn("maintenance/enable", actions)

    def test_capability_summary_exposes_roles_and_actions(self):
        """TASK-3-3-2-1: capability summaries describe allowed roles and actions."""

        summary = summarize_agent_capabilities()
        self.assertIn("roles", summary)
        self.assertIn("operator", summary["roles"])
        self.assertIn("branding/apply", summary["actions"])

    def test_agent_source_does_not_expose_privileged_hook_or_automation_routes(self):
        """TASK-3-3-3-2: node-agent avoids advertising privileged install endpoints."""

        source = Path("apps/node_agent/api.py").read_text(encoding="utf-8")
        self.assertNotIn('/hooks/install', source)
        self.assertNotIn('/automation/install', source)

    def test_agent_source_mentions_capabilities_in_summary_contract(self):
        """TASK-3-3-3-1: node-agent summary contract exposes capabilities metadata."""

        source = Path("apps/node_agent/api.py").read_text(encoding="utf-8")
        self.assertIn('"capabilities"', source)
        self.assertIn('/branding/apply', source)


if __name__ == "__main__":
    unittest.main()
