#!/bin/bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bootstrap-common.inc.sh"
PYTHONPATH="$REPO_ROOT/src" python3 -m nexora_core.bootstrap apply-augment \
  --repo-root "$REPO_ROOT" \
  --state-path /opt/nexora/var/state.json \
  --domain "$DOMAIN" \
  --path-url "${PATH_URL:-/nexora}"
if [[ "${CONFIRM_AUGMENT:-no}" != "yes" ]]; then
  echo "Current state imported to /opt/nexora/var/state.json"
  echo "No package change applied yet. Re-run with CONFIRM_AUGMENT=yes to install/upgrade Nexora."
  exit 0
fi
if yunohost app list --output-as json 2>/dev/null | grep -q '"nexora-platform"'; then
  yunohost app upgrade nexora-platform
else
  if [[ "$(path_conflict "$DOMAIN" "$PATH_URL")" == "yes" ]]; then
    echo "Requested DOMAIN/PATH already used by another YunoHost app." >&2
    echo "Suggested free path: $(suggest_path "$DOMAIN" "$PATH_URL")" >&2
    exit 1
  fi
  yunohost app install "$PACKAGE_DIR" -a "domain=${DOMAIN}&path=${PATH_URL}"
fi
echo "Nexora augment mode complete."
