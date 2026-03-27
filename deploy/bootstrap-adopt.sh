#!/bin/bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bootstrap-common.inc.sh"
mkdir -p /opt/nexora/var
PYTHONPATH="$REPO_ROOT/src" python3 -m nexora_core.bootstrap adoption-report \
  --repo-root "$REPO_ROOT" \
  --state-path /opt/nexora/var/state.json \
  --domain "$DOMAIN" \
  --path-url "${PATH_URL:-/nexora}" > /opt/nexora/var/adoption-report.json
if ! python3 - <<'PY' /opt/nexora/var/adoption-report.json
import json, sys
payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
raise SystemExit(0 if payload.get("result", {}).get("report", {}).get("safe_to_install") else 1)
PY
then
  FREE_PATH="$(suggest_path "$DOMAIN" "${PATH_URL:-/nexora}")"
  BLOCKERS="$(python3 - <<'PY' /opt/nexora/var/adoption-report.json
import json, sys
payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
report = payload.get("result", {}).get("report", {})
items = [c.get("type", "unknown") for c in report.get("blocking_collisions", []) if isinstance(c, dict)]
print(",".join(items))
PY
)"
  echo "Adoption prechecks detected blocking collisions: ${BLOCKERS:-unknown}." >&2
  echo "See /opt/nexora/var/adoption-report.json" >&2
  echo "Suggested free path: ${FREE_PATH}" >&2
  exit 1
fi
if [[ "${CONFIRM_ADOPT:-no}" != "yes" ]]; then
  echo "Adoption report generated at /opt/nexora/var/adoption-report.json"
  echo "No change applied yet. Re-run with CONFIRM_ADOPT=yes to install Nexora on this populated YunoHost."
  exit 0
fi
PYTHONPATH="$REPO_ROOT/src" python3 -m nexora_core.bootstrap apply-adoption \
  --repo-root "$REPO_ROOT" \
  --state-path /opt/nexora/var/state.json \
  --domain "$DOMAIN" \
  --path-url "${PATH_URL:-/nexora}"
yunohost app install "$PACKAGE_DIR" -a "domain=${DOMAIN}&path=${PATH_URL}"
echo "Nexora adopted this existing YunoHost. Review /opt/nexora/var/adoption-report.json"
