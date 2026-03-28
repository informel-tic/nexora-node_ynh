from __future__ import annotations

import unittest

from nexora_node_sdk.edge import apply_nginx_lb
from nexora_node_sdk.failover import (
    apply_failover_nginx,
    apply_maintenance_mode,
    generate_failover_plan,
    generate_keepalived_config,
    list_health_check_strategies,
    remove_maintenance_mode,
)


class FailoverExtendedTests(unittest.TestCase):
    def test_generate_failover_plan_requires_two_nodes(self):
        report = generate_failover_plan([], [{"node_id": "a"}])
        self.assertIn("error", report)

    def test_generate_keepalived_config_mentions_vip(self):
        config = generate_keepalived_config("10.0.0.10", "a", "b")
        self.assertIn("10.0.0.10", config)

    def test_list_health_check_strategies_is_non_empty(self):
        self.assertTrue(list_health_check_strategies())

    def test_apply_nginx_lb_rejects_invalid_domain(self):
        result = apply_nginx_lb("server {}", "bad/domain")
        self.assertFalse(result["success"])
        self.assertIn("Invalid domain", result["error"])

    def test_apply_nginx_lb_requires_existing_yunohost_include_dir(self):
        result = apply_nginx_lb("server {}", "example.org")
        self.assertFalse(result["success"])
        self.assertIn("YunoHost-managed scope", result["error"])

    def test_apply_failover_nginx_rejects_invalid_domain_with_structured_error(self):
        result = apply_failover_nginx("demoapp", "primary.internal", "secondary.internal", "bad/domain")
        self.assertFalse(result["success"])
        self.assertIn("Invalid domain", result["error"])

    def test_apply_failover_nginx_requires_existing_yunohost_include_dir(self):
        result = apply_failover_nginx("demoapp", "primary.internal", "secondary.internal", "example.org")
        self.assertFalse(result["success"])
        self.assertIn("YunoHost-managed scope", result["error"])

    def test_apply_maintenance_mode_rejects_invalid_domain_with_structured_error(self):
        result = apply_maintenance_mode("bad/domain")
        self.assertFalse(result["success"])
        self.assertIn("Invalid domain", result["error"])

    def test_remove_maintenance_mode_requires_existing_yunohost_include_dir(self):
        result = remove_maintenance_mode("example.org")
        self.assertFalse(result["success"])
        self.assertIn("YunoHost-managed scope", result["error"])


if __name__ == "__main__":
    unittest.main()
