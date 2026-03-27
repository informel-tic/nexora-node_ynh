from __future__ import annotations

import unittest
from pathlib import Path


class NodeCIWorkflowTests(unittest.TestCase):
    def test_ci_workflow_is_node_scoped(self):
        source = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("docs-quality", source)
        self.assertIn("tests:", source)
        self.assertIn("test_package_contract.py", source)
        self.assertNotIn("nightly-operator-e2e", source)

    def test_package_lint_workflow_is_present(self):
        source = Path(".github/workflows/package-lint.yml").read_text(encoding="utf-8")
        self.assertIn("ynh-package/manifest.toml", source)


if __name__ == "__main__":
    unittest.main()