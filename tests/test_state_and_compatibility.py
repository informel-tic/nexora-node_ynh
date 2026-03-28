from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest.mock
import unittest
from pathlib import Path

from nexora_node_sdk import compatibility
from nexora_node_sdk.compatibility import (
    _simple_yaml_load,
    assess_compatibility,
    load_compatibility_matrix,
    resolve_compatibility_matrix_path,
)
from nexora_node_sdk.identity import generate_fleet_id, generate_node_credentials, generate_node_id
from nexora_node_sdk.state import StateStore, transition_node_status
from nexora_node_sdk.version import NEXORA_VERSION


class CLITests(unittest.TestCase):
    def test_cli_compatibility_subcommand_uses_current_interpreter(self):
        proc = subprocess.run(
            [sys.executable, '-m', 'yunohost_mcp.cli', 'compatibility'],
            env={**os.environ, 'PYTHONPATH': 'src', 'PYTHONIOENCODING': 'utf-8'},
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(payload['meta']['version'], 2)
        self.assertEqual(payload['releases']['2.0.0']['pinning_policy']['exact_minor'], '12.1')


class CompatibilityTests(unittest.TestCase):
    def test_resolve_compatibility_matrix_prefers_repo_root_file(self):
        path = resolve_compatibility_matrix_path(Path('.'))
        self.assertEqual(path, Path('compatibility.yaml'))

    def test_assess_compatibility_accepts_supported_exact_minor(self):
        matrix = load_compatibility_matrix(Path('compatibility.yaml'))
        report = assess_compatibility('2.0.0', '12.1.2', matrix=matrix)
        self.assertEqual(report['status'], 'tested')
        self.assertTrue(report['bootstrap_allowed'])

    def test_assess_compatibility_rejects_unknown_major(self):
        matrix = load_compatibility_matrix(Path('compatibility.yaml'))
        # Version 10.x has no exact match and no prefix range — must be unknown/blocked
        report = assess_compatibility('2.0.0', '10.0.0', matrix=matrix)
        self.assertFalse(report['bootstrap_allowed'])
        self.assertIn('version_not_listed', report['reasons'])

    def test_assess_compatibility_exposes_capability_verdicts_for_experimental_prefix(self):
        matrix = load_compatibility_matrix(Path('compatibility.yaml'))
        # YunoHost 13.x (Trixie) — experimental via prefix, observe-only (bootstrap blocked by exact_minor policy)
        report = assess_compatibility('2.0.0', '13.0.0', matrix=matrix)
        self.assertEqual(report['support_tier'], 'experimental')
        self.assertEqual(report['overall_status'], 'observe_only')
        self.assertTrue(report['capability_verdicts']['observe']['allowed'])
        self.assertFalse(report['capability_verdicts']['bootstrap']['allowed'])
        self.assertIn('observe', report['allowed_capabilities'])
        self.assertNotIn('bootstrap', report['allowed_capabilities'])
        self.assertTrue(report['manual_review_required'])
        self.assertIn('experimental_version', report['reasons'])

    def test_assess_compatibility_accepts_yunohost_11x_retrocompat(self):
        matrix = load_compatibility_matrix(Path('compatibility.yaml'))
        # YunoHost 11.x — experimental via prefix, observe-only (bootstrap blocked by exact_minor policy)
        report = assess_compatibility('2.0.0', '11.2.8', matrix=matrix)
        self.assertEqual(report['support_tier'], 'experimental')
        self.assertFalse(report['bootstrap_allowed'])
        self.assertTrue(report['manual_review_required'])
        self.assertIn('experimental_version', report['reasons'])

    def test_assess_compatibility_accepts_all_12x_via_prefix(self):
        matrix = load_compatibility_matrix(Path('compatibility.yaml'))
        # 12.1.x patch levels are supported with bootstrap; other 12.x are experimental/observe-only
        for version in ('12.1.39',):
            report = assess_compatibility('2.0.0', version, matrix=matrix)
            self.assertTrue(report['bootstrap_allowed'], f"bootstrap must be allowed for {version}")
            self.assertIn(report['support_tier'], ('tested', 'supported'))
        for version in ('12.0.0', '12.2.5', '12.99.0'):
            report = assess_compatibility('2.0.0', version, matrix=matrix)
            self.assertFalse(report['bootstrap_allowed'], f"bootstrap must be blocked for {version}")
            self.assertEqual(report['support_tier'], 'experimental')

    def test_assess_compatibility_marks_supported_minor_blueprint_as_manual_review(self):
        matrix = load_compatibility_matrix(Path('compatibility.yaml'))
        report = assess_compatibility('2.0.0', '12.1.1', matrix=matrix)
        self.assertEqual(report['support_tier'], 'supported')
        self.assertTrue(report['capability_verdicts']['install_app']['allowed'])
        self.assertFalse(report['capability_verdicts']['deploy_blueprint']['allowed'])
        self.assertTrue(report['capability_verdicts']['deploy_blueprint']['requires_manual_review'])

    def test_simple_yaml_loader_supports_block_style_capability_lists(self):
        matrix = _simple_yaml_load(Path('compatibility.yaml').read_text(encoding='utf-8'))
        capabilities = matrix['releases']['2.0.0']['capabilities']
        self.assertEqual(capabilities['install_app']['allowed_statuses'], ['tested', 'supported', 'experimental'])
        self.assertEqual(capabilities['deploy_blueprint']['manual_review_statuses'], ['supported', 'experimental'])


class StateLifecycleTests(unittest.TestCase):
    def test_transition_node_status_valid_path(self):
        node = {'node_id': 'node-1', 'hostname': 'node-1', 'status': 'discovered'}
        node = transition_node_status(node, 'bootstrap_pending')
        node = transition_node_status(node, 'agent_installed')
        node = transition_node_status(node, 'attested')
        node = transition_node_status(node, 'registered')
        self.assertEqual(node['status'], 'registered')
        self.assertIn('healthy', node['allowed_transitions'])

    def test_transition_node_status_rejects_invalid_jump(self):
        node = {'node_id': 'node-1', 'hostname': 'node-1', 'status': 'discovered'}
        with self.assertRaises(ValueError):
            transition_node_status(node, 'healthy')

    def test_state_store_normalizes_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            store = StateStore(path)
            store.save({'nodes': [{'node_id': 'node-1', 'hostname': 'n1'}]})
            data = store.load()
            self.assertEqual(data['nodes'][0]['status'], 'discovered')
            self.assertIn('bootstrap_pending', data['nodes'][0]['allowed_transitions'])

    def test_state_store_surfaces_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            path.write_text('{invalid json', encoding='utf-8')
            data = StateStore(path).load()
            self.assertEqual(data['_state_warning']['code'], 'state_parse_failed')
            self.assertEqual(data['nodes'], [])


class IdentityTests(unittest.TestCase):
    @unittest.mock.patch('nexora_node_sdk.identity._run_openssl')
    def test_identity_generation(self, mock_openssl):
        with tempfile.TemporaryDirectory() as tmp:
            node_id = generate_node_id('node-01.example')
            fleet_id = generate_fleet_id(None)
            
            def side_effect(*args, **kwargs):
                (Path(tmp) / 'fleet-ca.key').touch()
                (Path(tmp) / 'fleet-ca.crt').touch()
                (Path(tmp) / f'{node_id}.key').touch()
                (Path(tmp) / f'{node_id}.crt').touch()
                (Path(tmp) / 'fleet-ca.srl').touch()
            mock_openssl.side_effect = side_effect

            creds = generate_node_credentials(node_id, fleet_id, Path(tmp))
            self.assertTrue(node_id.startswith('node-'))
            self.assertTrue(fleet_id.startswith('fleet-'))
            self.assertTrue(Path(creds['key_path']).exists())
            self.assertEqual(creds['fleet_id'], fleet_id)


class VersionTests(unittest.TestCase):
    def test_shared_version_constant_matches_current_release(self):
        self.assertEqual(NEXORA_VERSION, '2.0.0')


if __name__ == '__main__':
    unittest.main()
