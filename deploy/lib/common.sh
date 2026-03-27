#!/bin/bash
set -euo pipefail

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "This script must run as root." >&2
    exit 1
  fi
}

get_repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
}

count_existing_apps() {
  local raw
  raw="$(yunohost app list --output-as json 2>/dev/null || true)"
  python3 - <<'PY' "$raw"
import json, sys
raw = sys.argv[1]
try:
    data = json.loads(raw) if raw else {}
    print(len(data.get('apps', [])))
except Exception:
    print(0)
PY
}

path_conflict() {
  local domain="$1"
  local path="$2"
  local raw
  raw="$(yunohost app map --output-as json 2>/dev/null || true)"
  python3 - <<'PY' "$raw" "$domain" "$path"
import json, sys
raw, domain, path = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    data = json.loads(raw) if raw else {}
except Exception:
    print('no')
    raise SystemExit(0)
domain_map = data.get(domain, {}) if isinstance(data, dict) else {}
print('yes' if isinstance(domain_map, dict) and path in domain_map else 'no')
PY
}

suggest_path() {
  local domain="$1"
  local base="${2:-/nexora}"
  local candidate="$base"
  local n=1
  while [[ "$(path_conflict "$domain" "$candidate")" == "yes" ]]; do
    candidate="${base}-${n}"
    n=$((n+1))
  done
  echo "$candidate"
}
