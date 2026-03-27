#!/usr/bin/env bash
set -euo pipefail

# Fail if root contains test_* files that are not Python tests.
violations=()
while IFS= read -r -d '' path; do
  base="${path#./}"
  case "$base" in
    *.py) ;;
    *) violations+=("$base") ;;
  esac
done < <(find . -maxdepth 1 -type f -name 'test_*' -print0)

if (( ${#violations[@]} > 0 )); then
  echo "[ERROR] Non-Python test_* artifact(s) found at repository root:" >&2
  printf ' - %s\n' "${violations[@]}" >&2
  echo "Move these files to artifacts/tests/ (or .artifacts/tests/)." >&2
  exit 1
fi

echo "[OK] No non-Python test_* artifacts found at repository root."
