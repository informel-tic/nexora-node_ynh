#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/dist/offline-bundle}"
WHEEL_DIR="$OUT_DIR/wheels"
MANIFEST="$OUT_DIR/manifest.json"

mkdir -p "$WHEEL_DIR"

python3 -m pip wheel --wheel-dir "$WHEEL_DIR" "$ROOT"

NEXORA_WHEEL="$(find "$WHEEL_DIR" -maxdepth 1 -name 'nexora_platform-*.whl' | head -n1)"
if [[ -z "$NEXORA_WHEEL" ]]; then
  echo "Offline bundle build failed: nexora_platform wheel missing in $WHEEL_DIR" >&2
  exit 1
fi

echo "==> Validating wheel bundle installability"
VALIDATION_VENV="$(mktemp -d)"
trap 'rm -rf "$VALIDATION_VENV"' EXIT
python3 -m venv "$VALIDATION_VENV"
if [[ ! -x "$VALIDATION_VENV/bin/pip" ]]; then
  "$VALIDATION_VENV/bin/python" -m ensurepip --upgrade
fi
"$VALIDATION_VENV/bin/python" -m pip install --upgrade pip setuptools wheel
"$VALIDATION_VENV/bin/python" -m pip install --no-index --find-links "$WHEEL_DIR" "$NEXORA_WHEEL"

python3 - <<'PY' "$ROOT" "$WHEEL_DIR" "$MANIFEST"
import json
import hashlib
from pathlib import Path
import sys

root = Path(sys.argv[1])
wheel_dir = Path(sys.argv[2])
manifest_path = Path(sys.argv[3])

wheels = []
for whl in sorted(wheel_dir.glob("*.whl")):
    wheels.append({
        "file": whl.name,
        "sha256": hashlib.sha256(whl.read_bytes()).hexdigest(),
    })

manifest = {
    "format": 1,
    "generated_at_utc": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    "repo_root": str(root),
    "wheel_count": len(wheels),
    "wheels": wheels,
}
manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
PY

echo "Offline bundle generated in: $OUT_DIR"
echo "- wheels: $WHEEL_DIR"
echo "- manifest: $MANIFEST"
