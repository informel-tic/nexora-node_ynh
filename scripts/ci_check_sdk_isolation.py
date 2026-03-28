"""CI Gate: verify nexora_node_sdk never imports nexora_saas.

This script is run in CI to ensure the subscriber SDK package
has no dependency on SaaS-only modules.  It walks every .py file
in src/nexora_node_sdk/ and fails if any import references
nexora_saas.
"""
from __future__ import annotations

import ast
import pathlib
import sys


def check_sdk_isolation() -> list[str]:
    violations: list[str] = []
    sdk_root = pathlib.Path("src/nexora_node_sdk")
    if not sdk_root.exists():
        print(f"SKIP: {sdk_root} does not exist")
        return violations

    for p in sdk_root.rglob("*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            module: str | None = None
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "nexora_saas" in alias.name:
                        violations.append(f"{p}:{node.lineno}: import {alias.name}")
                continue
            if module and "nexora_saas" in module:
                violations.append(f"{p}:{node.lineno}: from {module} import ...")
    return violations


def main() -> None:
    violations = check_sdk_isolation()
    if violations:
        print("FAIL: nexora_node_sdk imports nexora_saas:")
        for v in violations:
            print(f"  {v}")
        sys.exit(1)
    print("OK: nexora_node_sdk is clean — no nexora_saas imports found")


if __name__ == "__main__":
    main()
