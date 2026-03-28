from __future__ import annotations

import unittest
from unittest.mock import patch

from nexora_node_sdk.admin_actions import deploy_blueprint
from nexora_node_sdk.blueprints import load_blueprints, resolve_blueprint_plan


class BlueprintPlanResolutionTests(unittest.TestCase):
    @patch("nexora_node_sdk.blueprints.build_install_preflight")
    def test_resolve_blueprint_plan_uses_subdomains_and_profile_defaults(self, mock_preflight):
        def side_effect(app_id: str, domain: str, path: str = "/", args: str = ""):
            return {
                "allowed": True,
                "status": "allowed",
                "warnings": [],
                "blocking_issues": [],
                "manual_review_required": False,
                "profile": {"app_id": app_id},
                "domain": domain,
                "path": path,
            }

        mock_preflight.side_effect = side_effect
        blueprint = next(bp for bp in load_blueprints("blueprints") if bp.slug == "pme")
        plan = resolve_blueprint_plan(blueprint, "example.org")
        self.assertTrue(plan["allowed"])
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["app_plans"][0]["target_domain"], "cloud.example.org")
        self.assertEqual(plan["app_plans"][0]["target_path"], "/")
        self.assertEqual(plan["app_plans"][1]["target_domain"], "mail.example.org")
        self.assertEqual(plan["app_plans"][1]["target_path"], "/")
        self.assertEqual(plan["app_plans"][2]["target_domain"], "portal.example.org")
        self.assertEqual(plan["app_plans"][2]["target_path"], "/")

    @patch("nexora_node_sdk.blueprints.build_install_preflight")
    def test_resolve_blueprint_plan_blocks_unprofiled_apps(self, mock_preflight):
        mock_preflight.return_value = {
            "allowed": True,
            "status": "allowed",
            "warnings": [],
            "blocking_issues": [],
            "manual_review_required": False,
            "profile": {"app_id": "nextcloud"},
            "domain": "example.org",
            "path": "/",
        }
        blueprint = next(bp for bp in load_blueprints("blueprints") if bp.slug == "msp")
        plan = resolve_blueprint_plan(blueprint, "example.org")
        self.assertFalse(plan["allowed"])
        self.assertEqual(plan["status"], "blocked")
        self.assertIn("app:borg", plan["blocking_issues"])


class BlueprintDeployExecutionTests(unittest.TestCase):
    @patch("nexora_node_sdk.admin_actions._ynh")
    @patch("nexora_node_sdk.admin_actions.install_app")
    @patch("nexora_node_sdk.admin_actions.resolve_blueprint_plan")
    def test_deploy_blueprint_executes_resolved_targets(self, mock_plan, mock_install, mock_ynh):
        mock_plan.return_value = {
            "allowed": True,
            "status": "ready",
            "warnings": [],
            "app_plans": [
                {"app": "nextcloud", "target_domain": "cloud.example.org", "target_path": "/"},
                {"app": "roundcube", "target_domain": "mail.example.org", "target_path": "/"},
            ],
        }
        mock_ynh.side_effect = [
            {"success": True, "data": {"domains": ["example.org"]}, "error": ""},
            {"success": True, "data": {}, "error": ""},
            {"success": True, "data": {}, "error": ""},
        ]
        mock_install.side_effect = [
            {"success": True, "error": ""},
            {"success": True, "error": ""},
        ]
        result = deploy_blueprint("pme", "example.org", ["nextcloud", "roundcube"], ["cloud", "mail"])
        self.assertTrue(result["success"])
        self.assertEqual(result["installed"], 2)
        self.assertEqual(mock_install.call_args_list[0].args, ("nextcloud", "cloud.example.org", "/"))
        self.assertEqual(mock_install.call_args_list[1].args, ("roundcube", "mail.example.org", "/"))
        self.assertEqual(mock_ynh.call_args_list[0].args, (["domain", "list"],))
        self.assertEqual(mock_ynh.call_args_list[1].args, (["domain", "add", "cloud.example.org"],))
        self.assertEqual(mock_ynh.call_args_list[2].args, (["domain", "add", "mail.example.org"],))
        self.assertEqual(result["domains"], [
            {"domain": "cloud.example.org", "created": True, "success": True, "error": ""},
            {"domain": "mail.example.org", "created": True, "success": True, "error": ""},
        ])
        self.assertIn("plan", result)

    @patch("nexora_node_sdk.admin_actions._ynh")
    @patch("nexora_node_sdk.admin_actions.install_app")
    @patch("nexora_node_sdk.admin_actions.resolve_blueprint_plan")
    def test_deploy_blueprint_stops_when_domain_preparation_fails(self, mock_plan, mock_install, mock_ynh):
        mock_plan.return_value = {
            "allowed": True,
            "status": "ready",
            "warnings": [],
            "app_plans": [
                {"app": "nextcloud", "target_domain": "cloud.example.org", "target_path": "/"},
            ],
        }
        mock_ynh.side_effect = [
            {"success": True, "data": {"domains": ["example.org"]}, "error": ""},
            {"success": False, "data": {}, "error": "domain add failed"},
        ]

        result = deploy_blueprint("pme", "example.org", ["nextcloud"], ["cloud"])

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "failed_to_prepare_domains:cloud.example.org")
        self.assertEqual(result["domains"], [
            {"domain": "cloud.example.org", "created": False, "success": False, "error": "domain add failed"},
        ])
        mock_install.assert_not_called()

    @patch("nexora_node_sdk.admin_actions.install_app")
    @patch("nexora_node_sdk.admin_actions.resolve_blueprint_plan")
    def test_deploy_blueprint_returns_plan_when_resolution_blocks(self, mock_plan, mock_install):
        mock_plan.return_value = {
            "allowed": False,
            "status": "blocked",
            "warnings": ["no_backup_detected"],
            "blocking_issues": ["app:borg"],
            "app_plans": [],
        }
        result = deploy_blueprint("msp", "example.org", ["nextcloud", "borg"], ["cloud", "backup"])
        self.assertFalse(result["success"])
        self.assertIn("app:borg", result["error"])
        self.assertIn("plan", result)
        mock_install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
