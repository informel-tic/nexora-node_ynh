#!/usr/bin/env bash
# Nexora Node Agent — one-liner subscriber installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/nexora/nexora-node/main/install.sh \
#     | ENROLLMENT_TOKEN=xxx CONTROL_PLANE_URL=https://saas.nexora.io bash
#
# Required environment:
#   ENROLLMENT_TOKEN       — one-time enrollment token issued by the SaaS control plane
#   CONTROL_PLANE_URL      — HTTPS URL of the Nexora SaaS control plane
#
# Optional:
#   NEXORA_INSTALL_DIR     — installation root (default: /opt/nexora)
#   NEXORA_AGENT_PORT      — node-agent listen port (default: 8443)

set -euo pipefail

# ── Validation ──────────────────────────────────────────────────

if [ -z "${ENROLLMENT_TOKEN:-}" ]; then
  echo "ERROR: ENROLLMENT_TOKEN is required." >&2
  echo "  Obtain one from your Nexora SaaS operator portal." >&2
  exit 1
fi

if [ -z "${CONTROL_PLANE_URL:-}" ]; then
  echo "ERROR: CONTROL_PLANE_URL is required." >&2
  exit 1
fi

# Enforce HTTPS
case "$CONTROL_PLANE_URL" in
  https://*) ;;
  *) echo "ERROR: CONTROL_PLANE_URL must use HTTPS." >&2; exit 1 ;;
esac

INSTALL_DIR="${NEXORA_INSTALL_DIR:-/opt/nexora}"
AGENT_PORT="${NEXORA_AGENT_PORT:-8443}"

echo "╔════════════════════════════════════════════╗"
echo "║   Nexora Node Agent — Subscriber Install   ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "  Control plane : $CONTROL_PLANE_URL"
echo "  Install dir   : $INSTALL_DIR"
echo "  Agent port    : $AGENT_PORT"
echo ""

# ── Prerequisites ───────────────────────────────────────────────

check_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: $1 is required but not installed." >&2
    exit 1
  }
}

check_command python3
check_command pip3
check_command curl
check_command systemctl

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
  echo "ERROR: Python >= 3.11 required (found $PYTHON_VERSION)." >&2
  exit 1
fi

# ── Install Package ─────────────────────────────────────────────

echo "[1/5] Installing nexora-node-agent package..."
pip3 install --quiet --upgrade nexora-node-agent

# ── Directory Setup ─────────────────────────────────────────────

echo "[2/5] Setting up directories..."
mkdir -p "$INSTALL_DIR/var"
mkdir -p "$INSTALL_DIR/etc"
mkdir -p "$INSTALL_DIR/log"

# Store enrollment config (restricted permissions)
printf '%s' "$ENROLLMENT_TOKEN" > "$INSTALL_DIR/var/enrollment-token"
chmod 0600 "$INSTALL_DIR/var/enrollment-token"

printf '%s' "$CONTROL_PLANE_URL" > "$INSTALL_DIR/var/control-plane-url"
chmod 0644 "$INSTALL_DIR/var/control-plane-url"

# ── Systemd Service ─────────────────────────────────────────────

echo "[3/5] Installing systemd service..."
cat > /etc/systemd/system/nexora-node-agent.service <<UNIT
[Unit]
Description=Nexora Node Agent
After=network-online.target yunohost-api.service
Wants=network-online.target
Documentation=https://github.com/nexora/nexora-node

[Service]
Type=simple
ExecStart=$(command -v nexora-node-agent)
Environment=NEXORA_ROOT=$INSTALL_DIR
Environment=NEXORA_DEPLOYMENT_SCOPE=subscriber
Environment=NEXORA_AGENT_PORT=$AGENT_PORT
Environment=NEXORA_CONTROL_PLANE_URL=$CONTROL_PLANE_URL
WorkingDirectory=$INSTALL_DIR
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=nexora-node-agent

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$INSTALL_DIR/var $INSTALL_DIR/log
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload

# ── Start Agent ─────────────────────────────────────────────────

echo "[4/5] Starting nexora-node-agent..."
systemctl enable nexora-node-agent
systemctl start nexora-node-agent

# ── Enrollment ──────────────────────────────────────────────────

echo "[5/5] Initiating enrollment..."
sleep 2

# The agent auto-enrolls on startup when enrollment-token is present.
# Wait for enrollment result.
MAX_WAIT=30
WAITED=0
while [ "$WAITED" -lt "$MAX_WAIT" ]; do
  if [ -f "$INSTALL_DIR/var/state.json" ]; then
    if python3 -c "
import json, sys
state = json.loads(open('$INSTALL_DIR/var/state.json').read())
if state.get('enrollment', {}).get('status') == 'enrolled':
    sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
      echo ""
      echo "✓ Enrollment successful!"
      echo "  Node agent is running on port $AGENT_PORT"
      echo "  Logs: journalctl -u nexora-node-agent -f"
      exit 0
    fi
  fi
  sleep 2
  WAITED=$((WAITED + 2))
done

echo ""
echo "⚠ Enrollment is still pending (agent started but enrollment may take longer)."
echo "  Check status: systemctl status nexora-node-agent"
echo "  Check logs:   journalctl -u nexora-node-agent -f"
exit 0
