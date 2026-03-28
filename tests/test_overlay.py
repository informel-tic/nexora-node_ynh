"""Tests for Nexora overlay manager — clean rollback, manifest tracking, overlay status."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Patch overlay paths before import so tests don't hit real filesystem
_tmpdir = tempfile.mkdtemp(prefix="nexora_overlay_test_")
_OVERLAY_DIR = Path(_tmpdir) / "overlay"
_MANIFEST_PATH = _OVERLAY_DIR / "manifest.json"
_DOCKER_COMPOSE_DIR = _OVERLAY_DIR / "docker"
_NGINX_SNIPPETS_DIR = _OVERLAY_DIR / "nginx"
_CRON_DIR = _OVERLAY_DIR / "cron"
_SYSTEMD_DIR = _OVERLAY_DIR / "systemd"


class TestOverlayManifest(unittest.TestCase):
    """Test overlay manifest CRUD operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="nexora_overlay_")
        self.overlay_dir = Path(self.tmpdir) / "overlay"
        self.manifest_path = self.overlay_dir / "manifest.json"

        # Patch paths
        self._patches = [
            patch("nexora_core.overlay.OVERLAY_DIR", self.overlay_dir),
            patch("nexora_core.overlay.OVERLAY_MANIFEST_PATH", self.manifest_path),
            patch("nexora_core.overlay.DOCKER_COMPOSE_DIR", self.overlay_dir / "docker"),
            patch("nexora_core.overlay.NGINX_SNIPPETS_DIR", self.overlay_dir / "nginx"),
            patch("nexora_core.overlay.CRON_DIR", self.overlay_dir / "cron"),
            patch("nexora_core.overlay.SYSTEMD_DIR", self.overlay_dir / "systemd"),
        ]
        for p in self._patches:
            p.start()

        from nexora_core import overlay
        self.overlay = overlay

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_manifest_empty(self):
        """Loading manifest when no file exists returns empty template."""
        manifest = self.overlay.load_manifest()
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["components"], [])
        self.assertFalse(manifest["docker_installed_by_nexora"])
        self.assertTrue(manifest["rollback_safe"])
        self.assertIn("created_at", manifest)

    def test_save_and_reload_manifest(self):
        """Saved manifest is reloadable and contains updated_at."""
        manifest = self.overlay.load_manifest()
        manifest["docker_installed_by_nexora"] = True
        self.overlay.save_manifest(manifest)

        self.assertTrue(self.manifest_path.exists())
        reloaded = self.overlay.load_manifest()
        self.assertTrue(reloaded["docker_installed_by_nexora"])
        self.assertIn("updated_at", reloaded)

    def test_add_component(self):
        """Adding a component appends it to the manifest."""
        manifest = self.overlay.load_manifest()
        self.overlay._add_component(manifest, kind="docker-service", name="redis", detail={"port": 6379})
        self.assertEqual(len(manifest["components"]), 1)
        self.assertEqual(manifest["components"][0]["kind"], "docker-service")
        self.assertEqual(manifest["components"][0]["name"], "redis")
        self.assertEqual(manifest["components"][0]["detail"]["port"], 6379)
        self.assertIn("installed_at", manifest["components"][0])

    def test_remove_component(self):
        """Removing a component filters it out of the manifest."""
        manifest = self.overlay.load_manifest()
        self.overlay._add_component(manifest, kind="docker-service", name="redis")
        self.overlay._add_component(manifest, kind="docker-service", name="postgres")
        self.assertEqual(len(manifest["components"]), 2)

        removed = self.overlay._remove_component(manifest, kind="docker-service", name="redis")
        self.assertTrue(removed)
        self.assertEqual(len(manifest["components"]), 1)
        self.assertEqual(manifest["components"][0]["name"], "postgres")

    def test_remove_nonexistent_component(self):
        """Removing a component that doesn't exist returns False."""
        manifest = self.overlay.load_manifest()
        removed = self.overlay._remove_component(manifest, kind="docker-service", name="nonexistent")
        self.assertFalse(removed)


class TestOverlayDocker(unittest.TestCase):
    """Test Docker overlay operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="nexora_overlay_docker_")
        self.overlay_dir = Path(self.tmpdir) / "overlay"
        self.manifest_path = self.overlay_dir / "manifest.json"

        self._patches = [
            patch("nexora_core.overlay.OVERLAY_DIR", self.overlay_dir),
            patch("nexora_core.overlay.OVERLAY_MANIFEST_PATH", self.manifest_path),
            patch("nexora_core.overlay.DOCKER_COMPOSE_DIR", self.overlay_dir / "docker"),
            patch("nexora_core.overlay.NGINX_SNIPPETS_DIR", self.overlay_dir / "nginx"),
            patch("nexora_core.overlay.CRON_DIR", self.overlay_dir / "cron"),
            patch("nexora_core.overlay.SYSTEMD_DIR", self.overlay_dir / "systemd"),
        ]
        for p in self._patches:
            p.start()

        from nexora_core import overlay
        self.overlay = overlay

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("nexora_core.overlay._run_cmd")
    def test_docker_is_installed_true(self, mock_cmd):
        mock_cmd.return_value = {"ok": True, "out": "24.0.7", "err": ""}
        self.assertTrue(self.overlay.docker_is_installed())

    @patch("nexora_core.overlay._run_cmd")
    def test_docker_is_installed_false(self, mock_cmd):
        mock_cmd.return_value = {"ok": False, "out": "", "err": "command not found"}
        self.assertFalse(self.overlay.docker_is_installed())

    @patch("nexora_core.overlay._run_cmd")
    def test_install_docker_engine_already_installed(self, mock_cmd):
        mock_cmd.return_value = {"ok": True, "out": "24.0.7", "err": ""}
        result = self.overlay.install_docker_engine()
        self.assertFalse(result["changed"])
        self.assertIn("already installed", result["message"])

    @patch("nexora_core.overlay._run_cmd")
    def test_uninstall_docker_not_by_nexora(self, mock_cmd):
        """Don't remove Docker if it was not installed by Nexora."""
        manifest = self.overlay.load_manifest()
        manifest["docker_installed_by_nexora"] = False
        self.overlay.save_manifest(manifest)

        result = self.overlay.uninstall_docker_engine()
        self.assertFalse(result["changed"])
        self.assertIn("not installed by Nexora", result["message"])


class TestOverlayStatus(unittest.TestCase):
    """Test overlay_status reporting."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="nexora_overlay_status_")
        self.overlay_dir = Path(self.tmpdir) / "overlay"
        self.manifest_path = self.overlay_dir / "manifest.json"

        self._patches = [
            patch("nexora_core.overlay.OVERLAY_DIR", self.overlay_dir),
            patch("nexora_core.overlay.OVERLAY_MANIFEST_PATH", self.manifest_path),
            patch("nexora_core.overlay.DOCKER_COMPOSE_DIR", self.overlay_dir / "docker"),
            patch("nexora_core.overlay.NGINX_SNIPPETS_DIR", self.overlay_dir / "nginx"),
            patch("nexora_core.overlay.CRON_DIR", self.overlay_dir / "cron"),
            patch("nexora_core.overlay.SYSTEMD_DIR", self.overlay_dir / "systemd"),
        ]
        for p in self._patches:
            p.start()

        from nexora_core import overlay
        self.overlay = overlay

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_status_empty(self):
        status = self.overlay.overlay_status()
        self.assertFalse(status["overlay_active"])
        self.assertEqual(status["component_count"], 0)
        self.assertFalse(status["docker_installed_by_nexora"])
        self.assertTrue(status["rollback_safe"])


class TestFullRollback(unittest.TestCase):
    """Test full overlay rollback — the critical unenrollment path."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="nexora_overlay_rollback_")
        self.overlay_dir = Path(self.tmpdir) / "overlay"
        self.manifest_path = self.overlay_dir / "manifest.json"

        self._patches = [
            patch("nexora_core.overlay.OVERLAY_DIR", self.overlay_dir),
            patch("nexora_core.overlay.OVERLAY_MANIFEST_PATH", self.manifest_path),
            patch("nexora_core.overlay.DOCKER_COMPOSE_DIR", self.overlay_dir / "docker"),
            patch("nexora_core.overlay.NGINX_SNIPPETS_DIR", self.overlay_dir / "nginx"),
            patch("nexora_core.overlay.CRON_DIR", self.overlay_dir / "cron"),
            patch("nexora_core.overlay.SYSTEMD_DIR", self.overlay_dir / "systemd"),
        ]
        for p in self._patches:
            p.start()

        from nexora_core import overlay
        self.overlay = overlay

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("nexora_core.overlay._run_cmd")
    def test_full_rollback_empty(self, mock_cmd):
        """Rollback on empty overlay completes without error."""
        mock_cmd.return_value = {"ok": True, "out": "", "err": ""}
        result = self.overlay.full_overlay_rollback()
        self.assertTrue(result["rollback_complete"])
        self.assertIn("restored", result["message"].lower())

    @patch("nexora_core.overlay._run_cmd")
    def test_rollback_preserves_external_docker(self, mock_cmd):
        """Rollback does NOT remove Docker if it was NOT installed by Nexora."""
        mock_cmd.return_value = {"ok": True, "out": "", "err": ""}

        self.overlay.deploy_overlay_service("redis", "---")

        result = self.overlay.full_overlay_rollback()
        self.assertTrue(result["rollback_complete"])
        self.assertEqual(result["removed"]["docker_engine"], [])


class TestManifestIntegrity(unittest.TestCase):
    """Contract tests for overlay manifest format."""

    def test_manifest_json_schema(self):
        """Verify the overlay.py source defines the expected manifest shape."""
        src = Path("src/nexora_core/overlay.py").read_text(encoding="utf-8")
        self.assertIn('"version"', src)
        self.assertIn('"components"', src)
        self.assertIn('"docker_installed_by_nexora"', src)
        self.assertIn('"rollback_safe"', src)

    def test_overlay_exports_critical_functions(self):
        """Verify overlay module exports the functions needed by the node agent API."""
        src = Path("src/nexora_core/overlay.py").read_text(encoding="utf-8")
        required = [
            "def load_manifest",
            "def save_manifest",
            "def install_docker_engine",
            "def uninstall_docker_engine",
            "def deploy_overlay_service",
            "def remove_overlay_service",
            "def full_overlay_rollback",
            "def overlay_status",
        ]
        for fn in required:
            self.assertIn(fn, src, f"Missing export: {fn}")


if __name__ == "__main__":
    unittest.main()
