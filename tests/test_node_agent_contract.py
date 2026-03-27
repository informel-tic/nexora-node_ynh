from __future__ import annotations

import unittest
from pathlib import Path


class NodeAgentContractTests(unittest.TestCase):
    def test_node_agent_routes_are_present(self):
        source = Path("apps/node_agent/api.py").read_text(encoding="utf-8")
        self.assertIn("/health", source)
        self.assertIn("/inventory", source)
        self.assertIn("TokenAuthMiddleware", source)

    def test_saas_surfaces_are_absent(self):
        self.assertFalse(Path("apps/control_plane").exists())
        self.assertFalse(Path("apps/console").exists())
        self.assertFalse(Path("src/yunohost_mcp").exists())


if __name__ == "__main__":
    unittest.main()