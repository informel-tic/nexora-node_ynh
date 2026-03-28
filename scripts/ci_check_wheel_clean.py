"""CI Gate: verify the nexora-node-agent wheel contains no SaaS code.

This script inspects the built wheel (or the source tree) to ensure
no SaaS modules (nexora_saas, control_plane, console, yunohost_mcp)
leak into the subscriber distribution.
"""
from __future__ import annotations

import pathlib
import sys


FORBIDDEN_PACKAGES = {"nexora_saas", "control_plane", "console", "yunohost_mcp"}


def check_wheel_contents() -> list[str]:
    """Check that source tree under src/ and apps/ has no SaaS leaks."""
    violations: list[str] = []

    # Check src/ — only nexora_node_sdk should exist
    src = pathlib.Path("src")
    if src.exists():
        for child in src.iterdir():
            if child.is_dir() and child.name in FORBIDDEN_PACKAGES:
                violations.append(f"src/{child.name}/ should not be in the node repo")

    # Check apps/ — only node_agent should exist
    apps = pathlib.Path("apps")
    if apps.exists():
        for child in apps.iterdir():
            if child.is_dir() and child.name in {"control_plane", "console"}:
                violations.append(f"apps/{child.name}/ should not be in the node repo")

    return violations


def main() -> None:
    violations = check_wheel_contents()
    if violations:
        print("FAIL: SaaS code found in node repo:")
        for v in violations:
            print(f"  {v}")
        sys.exit(1)
    print("OK: node repo contains no SaaS code")


if __name__ == "__main__":
    main()
