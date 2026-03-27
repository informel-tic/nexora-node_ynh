#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$ROOT/dist/vm-offline-kit}"
KIT_SCOPE="${KIT_SCOPE:-subscriber}"
KIT_DIR="$OUT_DIR/kit"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
KIT_NAME="nexora-vm-${KIT_SCOPE}-offline-kit-${STAMP}"
KIT_TAR="$OUT_DIR/${KIT_NAME}.tar.gz"
KIT_SHA="$KIT_TAR.sha256"

mkdir -p "$OUT_DIR"
rm -rf "$KIT_DIR"
mkdir -p "$KIT_DIR"

echo "==> Staging repository snapshot"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.build' \
  --exclude 'dist/vm-offline-kit' \
  "$ROOT/" "$KIT_DIR/$KIT_NAME/"

if [[ "$KIT_SCOPE" == "subscriber" ]]; then
  echo "==> Applying subscriber scope hardening (strip control-plane artifacts)"
  rm -rf "$KIT_DIR/$KIT_NAME/apps/control_plane"
  rm -rf "$KIT_DIR/$KIT_NAME/apps/console"
  rm -rf "$KIT_DIR/$KIT_NAME/ynh-package"
  rm -f "$KIT_DIR/$KIT_NAME/deploy/templates/nexora-control-plane.service"
  python3 - <<'PY' "$KIT_DIR/$KIT_NAME/pyproject.toml"
from pathlib import Path
import sys

pyproject = Path(sys.argv[1])
text = pyproject.read_text(encoding="utf-8")

replacements = (
    ('nexora-control-plane = "apps.control_plane.backend:main"\n', ""),
    ('"apps/control_plane", ', ""),
)
for old, new in replacements:
    if old not in text:
        raise SystemExit(f"expected pattern not found in {pyproject}: {old!r}")
    text = text.replace(old, new, 1)

pyproject.write_text(text, encoding="utf-8")
PY
  cat > "$KIT_DIR/$KIT_NAME/.nexora-kit-scope" <<'EOF'
scope=subscriber
profile=node-agent-only
EOF
else
  cat > "$KIT_DIR/$KIT_NAME/.nexora-kit-scope" <<'EOF'
scope=operator
profile=control-plane+node-agent
EOF
fi

echo "==> Building offline wheel bundle from scoped snapshot"
WHEEL_DIR="$KIT_DIR/$KIT_NAME/dist/offline-bundle/wheels"
MANIFEST="$KIT_DIR/$KIT_NAME/dist/offline-bundle/manifest.json"
mkdir -p "$WHEEL_DIR"
python3 -m pip wheel --wheel-dir "$WHEEL_DIR" "$KIT_DIR/$KIT_NAME"
NEXORA_WHEEL="$(find "$WHEEL_DIR" -maxdepth 1 -name 'nexora_platform-*.whl' | head -n1)"
if [[ -z "$NEXORA_WHEEL" ]]; then
  echo "Offline kit build failed: nexora_platform wheel missing in $WHEEL_DIR" >&2
  exit 1
fi

echo "==> Validating scoped wheel bundle installability"
VALIDATION_VENV="$(mktemp -d)"
trap 'rm -rf "$VALIDATION_VENV"' EXIT
python3 -m venv "$VALIDATION_VENV"
if [[ ! -x "$VALIDATION_VENV/bin/pip" ]]; then
  "$VALIDATION_VENV/bin/python" -m ensurepip --upgrade
fi
"$VALIDATION_VENV/bin/python" -m pip install --upgrade pip setuptools wheel
"$VALIDATION_VENV/bin/python" -m pip install --no-index --find-links "$WHEEL_DIR" "$NEXORA_WHEEL"

python3 - <<'PY' "$WHEEL_DIR" "$MANIFEST"
import json
import hashlib
from pathlib import Path
import sys

wheel_dir = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])

wheels = []
for whl in sorted(wheel_dir.glob("*.whl")):
    wheels.append({
        "file": whl.name,
        "sha256": hashlib.sha256(whl.read_bytes()).hexdigest(),
    })

manifest = {
    "format": 1,
    "generated_at_utc": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    "wheel_count": len(wheels),
    "wheels": wheels,
}
manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
PY

echo "==> Packaging uploadable artifact"
tar -czf "$KIT_TAR" -C "$KIT_DIR" "$KIT_NAME"
sha256sum "$KIT_TAR" > "$KIT_SHA"

echo "Offline VM kit created:"
echo "- archive: $KIT_TAR"
echo "- sha256:  $KIT_SHA"
echo
echo "Suggested VM-side flow:"
echo "1) Upload archive to VM via FTP/SFTP."
echo "2) Verify checksum: sha256sum -c $(basename "$KIT_SHA")"
echo "3) Extract: tar -xzf $(basename "$KIT_TAR")"
echo "4) Run bootstrap from extracted folder with local bundle:"
if [[ "$KIT_SCOPE" == "subscriber" ]]; then
  echo "   NEXORA_DEPLOYMENT_SCOPE=subscriber NEXORA_WHEEL_BUNDLE_DIR=./dist/offline-bundle SKIP_NETWORK_PRECHECKS=yes MODE=augment PROFILE=node-agent-only ENROLLMENT_MODE=pull TARGET_HOST=<node-host> ./deploy/bootstrap-full-platform.sh"
else
  echo "   NEXORA_DEPLOYMENT_SCOPE=operator NEXORA_WHEEL_BUNDLE_DIR=./dist/offline-bundle SKIP_NETWORK_PRECHECKS=yes MODE=adopt PROFILE=control-plane+node-agent ENROLLMENT_MODE=pull DOMAIN=<domain> PATH_URL=/nexora ./deploy/bootstrap-full-platform.sh"
fi
