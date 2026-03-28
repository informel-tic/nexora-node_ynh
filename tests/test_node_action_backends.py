from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexora_node_sdk.node_actions import ACTION_SPECS, NodeActionEngine, execute_node_action


class _FakeStateStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (Path(tempfile.gettempdir()) / "nexora-state.json")
        self.data = {
            "inventory_snapshots": [],
            "desired_state": {},
            "branding": {"brand_name": "Nexora", "accent": "#5B6CFF"},
            "identity": {"node_id": "node-a"},
            "node_action_events": [],
        }

    def load(self):
        return self.data

    def save(self, data):
        self.data = data


class _FakeSummary:
    def model_dump(self):
        return {
            "status": "healthy",
            "health_score": 88,
            "security_score": 77,
            "backups_count": 2,
        }


class _SummaryWithoutTenant:
    def model_dump(self):
        return {
            "status": "healthy",
            "health_score": 70,
            "security_score": 60,
            "backups_count": 1,
        }


class _FakeDashboard:
    def model_dump(self):
        return {"alerts": []}


class _FakeIdentity(dict):
    pass


class _FakeService:
    def __init__(self, path: Path | None = None):
        self.state = _FakeStateStore(path)
        self.invalidated = False

    def invalidate_cache(self, section: str | None = None):
        self.invalidated = True

    def local_inventory(self):
        return {
            "apps": {"apps": [{"id": "nextcloud"}]},
            "domains": {"domains": ["example.org"]},
            "permissions": {"permissions": {"mail.main": {"allowed": ["admins"]}}},
            "backups": {"archives": ["daily-1", "daily-2"]},
        }

    def inventory_slice(self, section):
        return self.local_inventory().get(section, {})

    def local_node_summary(self):
        return _FakeSummary()

    def compatibility_report(self):
        return {"assessment": {"bootstrap_allowed": True}}

    def dashboard(self):
        return _FakeDashboard()

    def identity(self):
        return _FakeIdentity(node_id="node-a")


class _FakeServiceWithoutTenantSummary(_FakeService):
    def local_node_summary(self):
        return _SummaryWithoutTenant()


class NodeActionBackendTests(unittest.TestCase):
    def test_action_engine_describes_capacity_and_params(self):
        engine = NodeActionEngine(_FakeService())
        description = engine.describe("docker/compose/apply")
        self.assertEqual(description["capacity_class"], "heavy")
        self.assertIn("content", description["required_params"])

    def test_inventory_refresh_persists_snapshot(self):
        service = _FakeService()
        result = execute_node_action(service, "inventory/refresh", dry_run=False)
        self.assertTrue(result["success"])
        self.assertTrue(service.invalidated)
        self.assertEqual(service.state.data["inventory_snapshots"][0]["kind"], "node-action-inventory-refresh")
        self.assertEqual(service.state.data["node_action_events"][-1]["action"], "inventory/refresh")
        self.assertIsNone(service.state.data["node_action_events"][-1]["tenant_id"])

    def test_inventory_refresh_tolerates_summary_without_tenant_attribute(self):
        service = _FakeServiceWithoutTenantSummary()
        result = execute_node_action(service, "inventory/refresh", dry_run=False)
        self.assertTrue(result["success"])
        self.assertIsNone(service.state.data["inventory_snapshots"][0]["tenant_id"])

    def test_permissions_sync_creates_baseline(self):
        service = _FakeService()
        result = execute_node_action(service, "permissions/sync", dry_run=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["sync_mode"], "create_baseline")
        self.assertIn("permissions", service.state.data["desired_state"])

    def test_hooks_install_reports_privileged_plan(self):
        service = _FakeService()
        result = execute_node_action(service, "hooks/install", dry_run=False)
        self.assertFalse(result["success"])
        self.assertTrue(result["requires_privileged_runtime"])
        self.assertEqual(result["privileged_plan"]["executor"], "control-plane")

    def test_automation_install_reports_privileged_plan(self):
        service = _FakeService()
        result = execute_node_action(service, "automation/install", dry_run=True)
        self.assertFalse(result["success"])
        self.assertEqual(result["privileged_plan"]["action"], "automation/install")

    def test_branding_apply_updates_runtime_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = _FakeService(Path(tmp) / "state.json")
            result = execute_node_action(service, "branding/apply", dry_run=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["branding"]["brand_name"], "Nexora")
        self.assertTrue(result["applied"]["success"])

    def test_pra_snapshot_persists_restore_plan(self):
        service = _FakeService()
        result = execute_node_action(service, "pra/snapshot", dry_run=False, params={"offsite_source": "s3://bucket"})
        self.assertTrue(result["success"])
        self.assertEqual(result["restore_plan"]["offsite_source"], "s3://bucket")
        self.assertEqual(service.state.data["pra_snapshots"][0]["kind"], "node-action-pra-snapshot")

    @patch("nexora_node_sdk.node_actions.apply_maintenance_mode", return_value={"success": True, "path": "/etc/nginx/conf.d/nexora-maintenance.conf"})
    def test_maintenance_enable_uses_real_backend(self, apply_mock):
        service = _FakeService()
        result = execute_node_action(
            service,
            "maintenance/enable",
            dry_run=False,
            params={"domain": "example.org", "message": "Upgrading"},
        )
        self.assertTrue(result["success"])
        apply_mock.assert_called_once_with("example.org", "Upgrading")
        self.assertEqual(result["maintenance_mode"], "enable")

    @patch("nexora_node_sdk.node_actions.remove_maintenance_mode", return_value={"success": True})
    def test_maintenance_disable_uses_real_backend(self, remove_mock):
        service = _FakeService()
        result = execute_node_action(
            service,
            "maintenance/disable",
            dry_run=False,
            params={"domain": "example.org"},
        )
        self.assertTrue(result["success"])
        remove_mock.assert_called_once_with("example.org")
        self.assertEqual(result["maintenance_mode"], "disable")

    @patch("nexora_node_sdk.node_actions.docker_compose_up", return_value={"success": True, "output": "started"})
    @patch("nexora_node_sdk.node_actions.write_compose_file", return_value={"written": "/tmp/docker-compose.yml", "size_bytes": 42})
    def test_docker_compose_apply_writes_and_starts_stack(self, write_mock, up_mock):
        service = _FakeService()
        result = execute_node_action(
            service,
            "docker/compose/apply",
            dry_run=False,
            params={"content": "services:\n  web:\n    image: nginx:stable", "path": "/tmp/docker-compose.yml", "detach": True},
        )
        self.assertTrue(result["success"])
        write_mock.assert_called_once()
        up_mock.assert_called_once_with("/tmp/docker-compose.yml", detach=True)

    def test_docker_compose_apply_enforces_payload_limit(self):
        service = _FakeService()
        huge_content = "x" * (ACTION_SPECS["docker/compose/apply"].max_payload_bytes + 1)
        result = execute_node_action(service, "docker/compose/apply", dry_run=False, params={"content": huge_content})
        self.assertFalse(result["success"])
        self.assertIn("capacity limit", result["error"])

    def test_audit_trail_redacts_opaque_and_nested_sensitive_params(self):
        service = _FakeService()
        params = {
            "content": "services:\n  db:\n    environment:\n      POSTGRES_PASSWORD: super-secret",
            "details": {
                "apiToken": "abc123",
                "labels": ["demo"],
            },
            "path": "/tmp/docker-compose.yml",
        }

        result = execute_node_action(service, "docker/compose/apply", dry_run=True, params=params)

        self.assertTrue(result["success"])
        self.assertTrue(result["audit"]["params"]["content"]["redacted"])
        self.assertEqual(result["audit"]["params"]["details"]["apiToken"]["redacted"], True)
        event = service.state.data["node_action_events"][-1]
        self.assertTrue(event["params"]["content"]["redacted"])
        self.assertEqual(event["params"]["details"]["apiToken"]["type"], "str")

    def test_healthcheck_runs_real_checks(self):
        service = _FakeService()
        result = execute_node_action(service, "healthcheck/run", dry_run=False)
        self.assertTrue(result["checks"]["compatibility"])
        self.assertTrue(result["checks"]["backups_present"])
        self.assertEqual(result["health_score"], 88)
        self.assertIn("trace_id", result)
        self.assertIn("audit", result)


if __name__ == "__main__":
    unittest.main()
