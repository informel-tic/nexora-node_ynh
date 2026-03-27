#!/bin/bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"
require_root
REPO_ROOT="$(get_repo_root)"
DOMAIN="${DOMAIN:-}"
PATH_URL="${PATH_URL:-/nexora}"
PACKAGE_DIR="${REPO_ROOT}/ynh-package"
VENV_DIR="/opt/nexora/venv"
STATE_DIR="/opt/nexora/var"
SYSTEMD_DIR="/etc/systemd/system"
LOG_DIR="/var/log/yunohost-mcp-server"
EXPORT_DIR="/tmp/nexora-export"
[[ -n "$DOMAIN" ]] || { echo "DOMAIN must be set"; exit 1; }

# Create service user if needed
if ! id nexora &>/dev/null; then
  useradd --system --home-dir /opt/nexora --shell /usr/sbin/nologin nexora
fi

mkdir -p /opt/nexora "$STATE_DIR" "$LOG_DIR" "$EXPORT_DIR"
chown nexora:nexora "$STATE_DIR" "$LOG_DIR" "$EXPORT_DIR"

# Generate API token if absent
if [[ ! -f "$STATE_DIR/api-token" ]]; then
  python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$STATE_DIR/api-token"
  chmod 600 "$STATE_DIR/api-token"
  chown nexora:nexora "$STATE_DIR/api-token"
  echo "API token generated at $STATE_DIR/api-token"
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
if [[ ! -x "$VENV_DIR/bin/pip" ]]; then
  "$VENV_DIR/bin/python" -m ensurepip --upgrade
fi
BUNDLE_DIR="${NEXORA_WHEEL_BUNDLE_DIR:-$REPO_ROOT/dist/offline-bundle}"
WHEEL_DIR="$BUNDLE_DIR/wheels"
if [[ -d "$WHEEL_DIR" ]] && compgen -G "$WHEEL_DIR/*.whl" > /dev/null; then
  NEXORA_WHEEL="$(find "$WHEEL_DIR" -maxdepth 1 -name 'nexora_platform-*.whl' | head -n1)"
  if [[ -z "$NEXORA_WHEEL" ]]; then
    echo "Offline bundle found but nexora_platform wheel is missing in $WHEEL_DIR" >&2
    exit 1
  fi
  echo "Installing Nexora from offline wheel bundle: $WHEEL_DIR"
  "$VENV_DIR/bin/python" -m pip install --no-index --find-links "$WHEEL_DIR" "$NEXORA_WHEEL"
else
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  "$VENV_DIR/bin/python" -m pip install "$REPO_ROOT"
fi
chown -R nexora:nexora /opt/nexora

install -m 0644 "$REPO_ROOT/deploy/templates/nexora-control-plane.service" "$SYSTEMD_DIR/nexora-control-plane.service"
install -m 0644 "$REPO_ROOT/deploy/templates/nexora-node-agent.service" "$SYSTEMD_DIR/nexora-node-agent.service"
systemctl daemon-reload
systemctl enable --now nexora-control-plane nexora-node-agent
SRC_ARCHIVE="$($REPO_ROOT/deploy/prepare-local-package.sh)"
SRC_DIR="$(dirname "$SRC_ARCHIVE")"
SRC_FILE="$(basename "$SRC_ARCHIVE")"
SRC_HTTP_PORT="$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"
python3 -m http.server "$SRC_HTTP_PORT" --bind 127.0.0.1 --directory "$SRC_DIR" >/tmp/nexora-source-http.log 2>&1 &
SRC_HTTP_PID="$!"
sleep 1
if ! kill -0 "$SRC_HTTP_PID" 2>/dev/null; then
  echo "Failed to start local source HTTP server for YunoHost package install." >&2
  exit 1
fi
SRC_URL="http://127.0.0.1:${SRC_HTTP_PORT}/${SRC_FILE}"
cp "$PACKAGE_DIR/manifest.toml" "$PACKAGE_DIR/manifest.toml.bak"
python3 - "$PACKAGE_DIR/manifest.toml" "$SRC_ARCHIVE" "$SRC_URL" <<'PY'
from pathlib import Path
import hashlib
import sys
manifest = Path(sys.argv[1])
src = Path(sys.argv[2])
src_url = sys.argv[3]
sha = hashlib.sha256(src.read_bytes()).hexdigest()
text = manifest.read_text()
text = text.replace("__LOCAL_SOURCE_URL__", src_url)
text = text.replace("__LOCAL_SOURCE_SHA256__", sha)
manifest.write_text(text)
PY
cleanup_manifest() {
  mv "$PACKAGE_DIR/manifest.toml.bak" "$PACKAGE_DIR/manifest.toml"
  if [[ -n "${SRC_HTTP_PID:-}" ]]; then
    kill "$SRC_HTTP_PID" 2>/dev/null || true
  fi
}
trap cleanup_manifest EXIT
