from __future__ import annotations

import unittest
from pathlib import Path


class NodePackageContractTests(unittest.TestCase):
    def test_required_ynh_package_files_exist(self):
        required = [
            "ynh-package/manifest.toml",
            "ynh-package/tests.toml",
            "ynh-package/scripts/install",
            "ynh-package/scripts/remove",
            "ynh-package/scripts/upgrade",
            "ynh-package/scripts/backup",
            "ynh-package/scripts/restore",
        ]
        for rel_path in required:
            self.assertTrue(Path(rel_path).exists(), rel_path)


if __name__ == "__main__":
    unittest.main()