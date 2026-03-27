#!/bin/bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
apps_count="$(count_existing_apps)"
if yunohost app list --output-as json 2>/dev/null | grep -q '"nexora-platform"'; then
  echo augment
elif [[ "$apps_count" == "0" ]]; then
  echo fresh
else
  echo adopt
fi
