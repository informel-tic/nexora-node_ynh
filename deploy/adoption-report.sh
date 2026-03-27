#!/bin/bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bootstrap-common.inc.sh"
python3 - <<PY
from pathlib import Path
import json
from nexora_core import NexoraService
service = NexoraService(Path("$REPO_ROOT"), Path("/opt/nexora/var/state.json"))
print(json.dumps(service.adoption_report("$DOMAIN", "$PATH_URL"), indent=2, ensure_ascii=False))
PY
