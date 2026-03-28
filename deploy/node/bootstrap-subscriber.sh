#!/usr/bin/env bash
# bootstrap-subscriber.sh — Nexora Node Agent bootstrap for subscribers
#
# This script is the offline/manual alternative to install.sh.
# It expects a local copy of the nexora-node package and configures
# the node agent for enrollment against a Nexora SaaS control plane.
#
# Usage:
#   ENROLLMENT_TOKEN=xxx CONTROL_PLANE_URL=https://saas.nexora.io \
#     bash deploy/node/bootstrap-subscriber.sh
#
# Environment:
#   ENROLLMENT_TOKEN       — (required) one-time enrollment token
#   CONTROL_PLANE_URL      — (required) HTTPS URL of the control plane
#   NEXORA_ROOT            — install root (default: /opt/nexora)
#   NEXORA_AGENT_PORT      — listen port (default: 8443)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Validate inputs ────────────────────────────────────────────

if [ -z "${ENROLLMENT_TOKEN:-}" ]; then
  echo "FATAL: ENROLLMENT_TOKEN not set." >&2
  exit 1
fi
if [ -z "${CONTROL_PLANE_URL:-}" ]; then
  echo "FATAL: CONTROL_PLANE_URL not set." >&2
  exit 1
fi
case "$CONTROL_PLANE_URL" in
  https://*) ;;
  *) echo "FATAL: CONTROL_PLANE_URL must use HTTPS." >&2; exit 1 ;;
esac

NEXORA_ROOT="${NEXORA_ROOT:-/opt/nexora}"
AGENT_PORT="${NEXORA_AGENT_PORT:-8443}"

echo "── Nexora Node Agent Bootstrap (subscriber) ──"
echo "  Repo root      : $REPO_ROOT"
echo "  Install root   : $NEXORA_ROOT"
echo "  Control plane  : $CONTROL_PLANE_URL"
echo "  Agent port     : $AGENT_PORT"
echo ""

# ── Python check ───────────────────────────────────────────────

PYTHON="python3"
PY_VER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  echo "FATAL: Python >= 3.11 required (found $PY_VER)." >&2
  exit 1
fi

# ── Install from local source ──────────────────────────────────

echo "[1/6] Installing nexora-node-agent from local source..."
pip3 install --quiet "$REPO_ROOT"

# ── Directory setup ────────────────────────────────────────────

echo "[2/6] Setting up $NEXORA_ROOT ..."
mkdir -p "$NEXORA_ROOT/var" "$NEXORA_ROOT/etc" "$NEXORA_ROOT/log"

# ── Write enrollment config ────────────────────────────────────

echo "[3/6] Writing enrollment configuration..."
printf '%s' "$ENROLLMENT_TOKEN" > "$NEXORA_ROOT/var/enrollment-token"
chmod 0600 "$NEXORA_ROOT/var/enrollment-token"

printf '%s' "$CONTROL_PLANE_URL" > "$NEXORA_ROOT/var/control-plane-url"
chmod 0644 "$NEXORA_ROOT/var/control-plane-url"

# ── Compatibility check ────────────────────────────────────────

echo "[4/6] Checking YunoHost compatibility..."
PYTHONPATH="$REPO_ROOT/src" $PYTHON -c "
from nexora_node_sdk.compatibility import assess_compatibility, load_compatibility_matrix
import subprocess, json

try:
    ver = subprocess.check_output(
        ['yunohost', 'tools', 'versions', '--output-as', 'json'],
        timeout=10
    )
    ynh_version = json.loads(ver).get('yunohost', {}).get('version', 'unknown')
except Exception:
    ynh_version = 'unknown'

matrix = load_compatibility_matrix()
result = assess_compatibility('2.0.0', ynh_version, matrix=matrix)
print(f'  YunoHost version : {ynh_version}')
print(f'  Compatibility    : {result.get(\"level\", \"unknown\")}')
if result.get('level') == 'incompatible':
    print('WARNING: YunoHost version is not compatible. Proceeding anyway.')
"

# ── Install systemd unit ───────────────────────────────────────

echo "[5/6] Installing systemd service..."
AGENT_BIN="$(command -v nexora-node-agent)"
sed -e "s|__NEXORA_ROOT__|$NEXORA_ROOT|g" \
    -e "s|__AGENT_PORT__|$AGENT_PORT|g" \
    -e "s|__CONTROL_PLANE_URL__|$CONTROL_PLANE_URL|g" \
    -e "s|__AGENT_BIN__|$AGENT_BIN|g" \
    "$SCRIPT_DIR/templates/nexora-node-agent.service" \
    > /etc/systemd/system/nexora-node-agent.service

systemctl daemon-reload
systemctl enable nexora-node-agent

# ── Start agent ────────────────────────────────────────────────

echo "[6/6] Starting nexora-node-agent..."
systemctl start nexora-node-agent

echo ""
echo "✓ Nexora node agent installed and started."
echo "  Enrollment will happen automatically on first heartbeat."
echo "  Status : systemctl status nexora-node-agent"
echo "  Logs   : journalctl -u nexora-node-agent -f"
