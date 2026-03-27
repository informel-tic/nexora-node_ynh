from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


class SharedCoreManifestTests(unittest.TestCase):
    def test_manifest_matches_current_files(self):
        manifest = json.loads(Path("SHARED_MODULES_MANIFEST.json").read_text(encoding="utf-8"))
        for rel_path, expected_hash in manifest["files"].items():
            path = Path(rel_path)
            self.assertTrue(path.exists(), rel_path)
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(actual_hash, expected_hash, rel_path)


if __name__ == "__main__":
    unittest.main()