from __future__ import annotations

import importlib
import inspect
import unittest


class SecurityAuditPublicContractTests(unittest.TestCase):
    """Regression tests for the public security_audit import contract.

    Linked to docs/CODEBASE_AUDIT_2026-03-24.md (section:
    "Régression API interne dans `security_audit`").
    """

    EXPECTED_CALLABLES: dict[str, tuple[str, ...]] = {
        "build_security_event": ("category", "action"),
        "append_security_event": ("state", "event"),
        "emit_security_event": ("state", "category", "action"),
        "append_security_event_to_file": ("state_path", "event"),
        "summarize_security_events": ("events",),
        "filter_security_events": ("events",),
    }

    EXPECTED_PUBLIC_SYMBOLS: set[str] = {
        *EXPECTED_CALLABLES.keys(),
        "SecurityJournal",
        "CRITICAL_ACTIONS",
        "SECURITY_CATEGORIES",
        "SECURITY_SEVERITIES",
        "VALID_CATEGORIES",
        "VALID_SEVERITIES",
    }

    def test_public_symbols_exist_and_are_importable(self):
        module = importlib.import_module("nexora_node_sdk.security_audit")
        for symbol_name in self.EXPECTED_PUBLIC_SYMBOLS:
            with self.subTest(symbol=symbol_name):
                self.assertTrue(hasattr(module, symbol_name))

    def test_expected_callables_have_compatible_minimal_signatures(self):
        module = importlib.import_module("nexora_node_sdk.security_audit")
        for symbol_name, required_params in self.EXPECTED_CALLABLES.items():
            with self.subTest(symbol=symbol_name):
                symbol = getattr(module, symbol_name)
                self.assertTrue(callable(symbol), f"{symbol_name} must be callable")

                signature = inspect.signature(symbol)
                parameter_names = tuple(signature.parameters.keys())
                self.assertEqual(parameter_names[: len(required_params)], required_params)

                for required_name in required_params:
                    parameter = signature.parameters[required_name]
                    self.assertIs(
                        parameter.default,
                        inspect._empty,
                        f"{symbol_name}.{required_name} must remain required",
                    )

    def test_module_defines___all___for_explicit_public_api(self):
        module = importlib.import_module("nexora_node_sdk.security_audit")
        self.assertTrue(hasattr(module, "__all__"))
        self.assertIsInstance(module.__all__, list)

        public_api = set(module.__all__)

        for symbol_name in self.EXPECTED_PUBLIC_SYMBOLS:
            with self.subTest(symbol=symbol_name):
                self.assertIn(symbol_name, public_api)
                self.assertTrue(hasattr(module, symbol_name))


if __name__ == "__main__":
    unittest.main()
