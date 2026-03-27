#!/bin/bash
set -euo pipefail

# ENG-01: Ensure YunoHost manifest version matches the Python single source of truth
python scripts/sync_version.py

PYTHONPATH=src python -m pytest tests/ -v --tb=short
git diff --quiet || {
  echo "Working tree must be clean before release (version sync or untracked changes preventing release)" >&2
  exit 1
}
python -m build
