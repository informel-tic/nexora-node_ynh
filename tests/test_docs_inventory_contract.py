from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class NodeDocsInventoryTests(unittest.TestCase):
    def test_inventory_entries_resolve(self):
        payload = yaml.safe_load(Path("docs/docs_inventory.yaml").read_text(encoding="utf-8"))
        for document in payload["documents"]:
            doc_path = Path(document["path"])
            self.assertTrue(doc_path.exists(), str(doc_path))
            for dependency in document.get("depends_on", []):
                self.assertTrue(Path(dependency).exists(), dependency)


if __name__ == "__main__":
    unittest.main()