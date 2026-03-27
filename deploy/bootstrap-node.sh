#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/deploy/lib/common.sh"
require_root

PROFILE="${PROFILE:-control-plane+node-agent}"
ENROLLMENT_MODE="${ENROLLMENT_MODE:-pull}"
TARGET_HOST="${TARGET_HOST:-localhost}"
DOMAIN="${DOMAIN:-}"
PATH_URL="${PATH_URL:-/nexora}"
MODE="${MODE:-augment}"
ALLOW_INSTALL_YUNOHOST="${ALLOW_INSTALL_YUNOHOST:-no}"
SKIP_NETWORK_PRECHECKS="${SKIP_NETWORK_PRECHECKS:-no}"
DEPLOYMENT_SCOPE="${NEXORA_DEPLOYMENT_SCOPE:-operator}"
BOOTSTRAP_LOG="${BOOTSTRAP_LOG:-/var/log/nexora/bootstrap-node.log}"
BOOTSTRAP_SLO_LOG="${BOOTSTRAP_SLO_LOG:-/var/log/nexora/bootstrap-slo.jsonl}"
PACKAGE_DIR="$ROOT/ynh-package"
VENV_DIR="/opt/nexora/venv"
STATE_DIR="/opt/nexora/var"
SYSTEMD_DIR="/etc/systemd/system"
CERTS_DIR="$STATE_DIR/certs"

mkdir -p "$(dirname "$BOOTSTRAP_LOG")" "$STATE_DIR" "$CERTS_DIR"
exec > >(tee -a "$BOOTSTRAP_LOG") 2>&1

BOOTSTRAP_STARTED_AT="$(date +%s)"
emit_bootstrap_slo() {
  local exit_code="$1"
  local ended_at duration status reason
  ended_at="$(date +%s)"
  duration="$((ended_at - BOOTSTRAP_STARTED_AT))"
  status="success"
  reason=""
  if [[ "$exit_code" -ne 0 ]]; then
    status="failure"
    reason="$(tail -n1 "$BOOTSTRAP_LOG" 2>/dev/null | tr -d '\r' | sed 's/"/\\"/g')"
  fi
  mkdir -p "$(dirname "$BOOTSTRAP_SLO_LOG")"
  python3 - <<'PY' \
    "$BOOTSTRAP_SLO_LOG" "$status" "$duration" "$MODE" "$PROFILE" "$ENROLLMENT_MODE" "$DEPLOYMENT_SCOPE" "$reason"
import json
import sys
from datetime import datetime, timezone

path, status, duration, mode, profile, enrollment_mode, scope, reason = sys.argv[1:9]
record = {
    "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "status": status,
    "duration_seconds": int(duration),
    "mode": mode,
    "profile": profile,
    "enrollment_mode": enrollment_mode,
    "deployment_scope": scope,
    "reason": reason if status == "failure" else "",
}
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
PY
}
trap 'emit_bootstrap_slo $?' EXIT

echo "==> Nexora bootstrap-node.sh"
echo "profile=$PROFILE enrollment_mode=$ENROLLMENT_MODE mode=$MODE target_host=$TARGET_HOST"

case "$PROFILE" in
  control-plane|node-agent-only|control-plane+node-agent) ;;
  *) echo "Unsupported PROFILE=$PROFILE" >&2; exit 1 ;;
esac

if [[ "$DEPLOYMENT_SCOPE" == "subscriber" && "$PROFILE" != "node-agent-only" ]]; then
  echo "Subscriber deployment scope only allows PROFILE=node-agent-only." >&2
  echo "Refusing control-plane installation in subscriber scope to avoid self-hosting full platform." >&2
  exit 1
fi

case "$ENROLLMENT_MODE" in
  push|pull) ;;
  *) echo "Unsupported ENROLLMENT_MODE=$ENROLLMENT_MODE" >&2; exit 1 ;;
esac

if [[ -z "$DOMAIN" && "$PROFILE" != "node-agent-only" ]]; then
  echo "Warning: DOMAIN is empty for control-plane profile."
  echo "Control-plane and node-agent services will be installed, but YunoHost app exposure is skipped."
fi

if [[ ! -r /etc/os-release ]]; then
  echo "Cannot read /etc/os-release" >&2
  exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "debian" || ! "${VERSION_ID:-}" =~ ^(11|12|13)([.].*)?$ ]]; then
  echo "Nexora bootstrap supports Debian 11.x/12.x/13.x on YunoHost nodes. Detected: ${ID:-unknown} ${VERSION_ID:-unknown}" >&2
  exit 1
fi
DEBIAN_MAJOR="${VERSION_ID%%.*}"
echo "OS precheck OK: ${PRETTY_NAME:-$ID $VERSION_ID} (debian_major=$DEBIAN_MAJOR)"
arch="$(dpkg --print-architecture)"
case "$arch" in
  amd64|arm64) ;;
  *) echo "Unsupported architecture: $arch" >&2; exit 1 ;;
esac
echo "Architecture OK: $arch"

required_cmds=(python3 jq systemctl getent timeout)
if [[ "$SKIP_NETWORK_PRECHECKS" != "yes" ]]; then
  required_cmds+=(curl)
fi
for cmd in "${required_cmds[@]}"; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing required command: $cmd" >&2; exit 1; }
done

if [[ "$SKIP_NETWORK_PRECHECKS" == "yes" ]]; then
  echo "Warning: SKIP_NETWORK_PRECHECKS=yes -> external DNS/connectivity prechecks are skipped."
else
  timeout 10 getent hosts deb.debian.org >/dev/null || { echo "DNS lookup failed for deb.debian.org" >&2; exit 1; }
  timeout 10 curl -fsSI https://repo.yunohost.org >/dev/null || { echo "Network reachability failed for https://repo.yunohost.org" >&2; exit 1; }
fi

timedatectl status --no-pager >/dev/null 2>&1 || echo "Warning: timedatectl unavailable, NTP check skipped"
disk_kb="$(df --output=avail / | tail -1 | tr -d ' ')"
if [[ -z "$disk_kb" || "$disk_kb" -lt 1048576 ]]; then
  echo "At least 1 GiB free disk space is required." >&2
  exit 1
fi
echo "Disk space OK: ${disk_kb} KiB available"

extract_semver() {
  python3 -c 'import re,sys; raw=sys.stdin.read().strip(); m=re.search(r"(\d+\.\d+(?:\.\d+)?)", raw); print(m.group(1) if m else "")'
}

yunohost_version=""
yunohost_present="no"
if command -v yunohost >/dev/null 2>&1; then
  yunohost_present="yes"
  yunohost_version="$(
    (yunohost tools version --output-as json 2>/dev/null || true) \
      | python3 -c 'import json,sys; raw=sys.stdin.read().strip(); data=json.loads(raw) if raw else {}; print(data.get("yunohost",{}).get("version",""))' 2>/dev/null
  )"
  if [[ -z "$yunohost_version" ]]; then
    yunohost_version="$( (yunohost --version 2>/dev/null || true) | extract_semver )"
  fi
fi
if [[ -z "$yunohost_version" ]]; then
  dpkg_yunohost_version="$( (dpkg-query -W -f='${Version}\n' yunohost 2>/dev/null || true) | extract_semver )"
  if [[ -n "$dpkg_yunohost_version" ]]; then
    yunohost_present="yes"
    yunohost_version="$dpkg_yunohost_version"
  fi
fi

if [[ -z "$yunohost_version" ]]; then
  if [[ "$yunohost_present" == "yes" ]]; then
    echo "YunoHost appears installed but version detection failed (tried: yunohost tools version, yunohost --version, dpkg-query)." >&2
    echo "Please verify YunoHost CLI health, then rerun bootstrap." >&2
    exit 1
  fi
  if [[ "$ALLOW_INSTALL_YUNOHOST" != "yes" ]]; then
    echo "YunoHost is not installed. Refusing to continue without ALLOW_INSTALL_YUNOHOST=yes." >&2
    echo "Official sequence: Debian 12 prechecks -> install YunoHost -> validate versions -> install Nexora -> attest -> register fleet." >&2
    exit 1
  fi
  echo "Installing YunoHost (fresh Debian 12 bootstrap)..."
  bash <(curl -fsSL https://install.yunohost.org)
  yunohost_version="$(yunohost tools version --output-as json | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("yunohost",{}).get("version",""))')"
fi

echo "Detected YunoHost version: ${yunohost_version:-unknown}"
compat_json="$(PYTHONPATH="$ROOT/src" python3 -m nexora_core.bootstrap assess \
  --repo-root "$ROOT" \
  --state-path "$STATE_DIR/state.json" \
  --profile "$PROFILE" \
  --enrollment-mode "$ENROLLMENT_MODE" \
  --mode "$MODE" \
  --yunohost-version "$yunohost_version" \
  --target-host "$TARGET_HOST" \
  --domain "$DOMAIN" \
  --path-url "$PATH_URL"
)"
echo "Compatibility assessment: $compat_json"
if ! python3 - <<'PY' "$compat_json"
import json, sys
report=json.loads(sys.argv[1])
raise SystemExit(0 if report.get('success') and report.get('compatibility', {}).get('bootstrap_allowed') else 1)
PY
then
  echo "Bootstrap aborted: YunoHost version is not compatible with Nexora 2.0.0 baseline." >&2
  exit 1
fi

COHERENCE_REPORT_PATH="$STATE_DIR/node-coherence-report.json"
python3 "$ROOT/scripts/node_coherence_audit.py" \
  --scope "$DEPLOYMENT_SCOPE" \
  --profile "$PROFILE" \
  --mode "$MODE" \
  --yunohost-version "$yunohost_version" \
  --output "$COHERENCE_REPORT_PATH"
echo "Node coherence report: $COHERENCE_REPORT_PATH"

if ! id nexora >/dev/null 2>&1; then
  useradd --system --home-dir /opt/nexora --shell /usr/sbin/nologin nexora
fi
mkdir -p /opt/nexora "$STATE_DIR" /tmp/nexora-export /var/log/yunohost-mcp-server "$CERTS_DIR"
chown -R nexora:nexora /opt/nexora /tmp/nexora-export /var/log/yunohost-mcp-server
mkdir -p /etc/nexora
if [[ ! -f /etc/nexora/api-token-roles.json ]]; then
  printf '{}\n' > /etc/nexora/api-token-roles.json
fi
chown root:root /etc/nexora/api-token-roles.json
chmod 600 /etc/nexora/api-token-roles.json

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
if [[ ! -x "$VENV_DIR/bin/pip" ]]; then
  "$VENV_DIR/bin/python" -m ensurepip --upgrade
fi

install_nexora_online() {
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  "$VENV_DIR/bin/python" -m pip install "$ROOT"
}

BUNDLE_DIR="${NEXORA_WHEEL_BUNDLE_DIR:-$ROOT/dist/offline-bundle}"
WHEEL_DIR="$BUNDLE_DIR/wheels"
ALLOW_ONLINE_WHEEL_FALLBACK="${NEXORA_ALLOW_ONLINE_WHEEL_FALLBACK:-yes}"
if [[ -d "$WHEEL_DIR" ]] && compgen -G "$WHEEL_DIR/*.whl" > /dev/null; then
  NEXORA_WHEEL="$(find "$WHEEL_DIR" -maxdepth 1 -name 'nexora_platform-*.whl' | head -n1)"
  if [[ -z "$NEXORA_WHEEL" ]]; then
    if [[ "$ALLOW_ONLINE_WHEEL_FALLBACK" == "yes" ]]; then
      echo "Offline bundle found but nexora_platform wheel is missing in $WHEEL_DIR; falling back to online install."
      install_nexora_online
    else
      echo "Offline bundle found but nexora_platform wheel is missing in $WHEEL_DIR" >&2
      echo "Set NEXORA_ALLOW_ONLINE_WHEEL_FALLBACK=yes to allow online fallback for test environments." >&2
      exit 1
    fi
  else
    echo "Installing Nexora from offline wheel bundle: $WHEEL_DIR"
    "$VENV_DIR/bin/python" -m pip install --no-index --find-links "$WHEEL_DIR" "$NEXORA_WHEEL"
  fi
else
  install_nexora_online
fi

install_service() {
  local service_name="$1"
  install -m 0644 "$ROOT/deploy/templates/${service_name}.service" "$SYSTEMD_DIR/${service_name}.service"
  systemctl daemon-reload
  systemctl enable --now "$service_name"
}

disable_service() {
  local service_name="$1"
  if systemctl list-unit-files | grep -q "^${service_name}\.service"; then
    systemctl disable --now "$service_name" || true
  fi
}

case "$PROFILE" in
  control-plane)
    install_service nexora-control-plane
    disable_service nexora-node-agent
    ;;
  node-agent-only)
    install_service nexora-node-agent
    disable_service nexora-control-plane
    ;;
  control-plane+node-agent)
    install_service nexora-control-plane
    install_service nexora-node-agent
    ;;
esac

bootstrap_result="$(PYTHONPATH="$ROOT/src" python3 -m nexora_core.bootstrap bootstrap-node \
  --repo-root "$ROOT" \
  --state-path "$STATE_DIR/state.json" \
  --profile "$PROFILE" \
  --enrollment-mode "$ENROLLMENT_MODE" \
  --mode "$MODE" \
  --yunohost-version "$yunohost_version" \
  --target-host "$TARGET_HOST" \
  --domain "$DOMAIN" \
  --path-url "$PATH_URL" \
  --enrolled-by "bootstrap-node.sh"
)"
echo "$bootstrap_result"
if ! python3 - <<'PY' "$bootstrap_result"
import json, sys
report=json.loads(sys.argv[1])
raise SystemExit(0 if report.get('success') else 1)
PY
then
  echo "Bootstrap state orchestration failed." >&2
  exit 1
fi

if [[ "$PROFILE" != "node-agent-only" && -n "$DOMAIN" ]]; then
  # YunoHost app service binds the same control-plane port; stop bootstrap unit first.
  disable_service nexora-control-plane
  if [[ "$MODE" == "fresh" ]]; then
    if [[ "$(path_conflict "$DOMAIN" "$PATH_URL")" == "yes" ]]; then
      echo "Requested DOMAIN/PATH already used by another YunoHost app." >&2
      echo "Suggested free path: $(suggest_path "$DOMAIN" "$PATH_URL")" >&2
      exit 1
    fi
    # Prepare local source archive and inject placeholders in manifest for offline-safe app install.
    SRC_ARCHIVE="$($ROOT/deploy/prepare-local-package.sh)"
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
    MANIFEST_PATH="$PACKAGE_DIR/manifest.toml"
    MANIFEST_BAK="$PACKAGE_DIR/manifest.toml.bak"
    cp "$MANIFEST_PATH" "$MANIFEST_BAK"
    python3 - "$MANIFEST_PATH" "$SRC_ARCHIVE" "$SRC_URL" <<'PY'
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
    if ! yunohost app install "$PACKAGE_DIR" -a "domain=${DOMAIN}&path=${PATH_URL}" --force; then
      kill "$SRC_HTTP_PID" 2>/dev/null || true
      mv "$MANIFEST_BAK" "$MANIFEST_PATH"
      exit 1
    fi
    kill "$SRC_HTTP_PID" 2>/dev/null || true
    mv "$MANIFEST_BAK" "$MANIFEST_PATH"
  elif [[ "$MODE" == "adopt" ]]; then
    bash "$ROOT/deploy/bootstrap-adopt.sh"
  elif [[ "$MODE" == "augment" ]]; then
    bash "$ROOT/deploy/bootstrap-augment.sh"
  else
    echo "Unknown MODE=$MODE" >&2
    exit 1
  fi
elif [[ "$PROFILE" != "node-agent-only" ]]; then
  echo "Skipping YunoHost package installation because DOMAIN is not set."
fi

echo "Bootstrap completed successfully. Log: $BOOTSTRAP_LOG"
