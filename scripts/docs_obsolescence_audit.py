#!/usr/bin/env python3
"""Detect obsolete docs and enforce their removal.

A doc is considered obsolete when its first 30 lines contain one of:
- "Status: Obsolete"
- "[OBSOLETE]"
- "DEPRECATED_DOC"

This script is intended for CI/docs-quality gates.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

DOCS_ROOT = Path("docs")
MARKERS = ("status: obsolete", "[obsolete]", "deprecated_doc")


def find_obsolete_docs() -> list[Path]:
    obsolete: list[Path] = []
    for path in sorted(DOCS_ROOT.rglob("*.md")):
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:30]).lower()
        if any(marker in head for marker in MARKERS):
            obsolete.append(path)
    return obsolete


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--enforce-removal",
        action="store_true",
        help="fail with non-zero exit code if obsolete docs are still present",
    )
    args = parser.parse_args()

    obsolete = find_obsolete_docs()
    if not obsolete:
        print("docs_obsolescence_audit: no obsolete docs detected")
        return 0

    print("docs_obsolescence_audit: obsolete docs detected:")
    for path in obsolete:
        print(f" - {path.as_posix()}")

    if args.enforce_removal:
        print("docs_obsolescence_audit: enforcement enabled -> remove obsolete docs before merge")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
