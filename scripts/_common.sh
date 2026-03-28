#!/bin/bash
source /usr/share/yunohost/helpers

# ---------------------------------------------------------------------------
# Nexora Node (Subscriber) — common helpers
# ---------------------------------------------------------------------------
# This file is used by the subscriber-only YunoHost package.
# It contains ONLY subscriber-relevant helpers — no control-plane logic.
# ---------------------------------------------------------------------------

NEXORA_OVERLAY_DIR="/opt/nexora/overlay"
NEXORA_OVERLAY_MANIFEST="$NEXORA_OVERLAY_DIR/manifest.json"
NEXORA_AGENT_PORT=38121

# ---------------------------------------------------------------------------
# Subscriber parameter validation
# ---------------------------------------------------------------------------

nexora_validate_subscriber_params() {
    if [[ -z "${saas_operator_url:-}" ]]; then
        ynh_die "saas_operator_url is required. Provide the URL of your Nexora SaaS operator."
    fi
    if [[ -z "${enrollment_token:-}" ]]; then
        ynh_die "enrollment_token is required. Obtain one from your Nexora operator."
    fi
    if [[ -z "${tenant_id:-}" ]]; then
        ynh_die "tenant_id is required. Obtain your tenant identifier from your Nexora operator."
    fi
}

# ---------------------------------------------------------------------------
# Subscriber state initialization
# ---------------------------------------------------------------------------

nexora_write_subscriber_state() {
    mkdir -p "$data_dir"
    if [ ! -f "$data_dir/state.json" ]; then
        cat > "$data_dir/state.json" <<JSON
{
  "identity": {
    "role": "subscriber-agent"
  },
  "deployment": {
    "scope": "subscriber",
    "profile": "node-agent-only",
    "saas_operator_url": "${saas_operator_url:-}",
    "tenant_id": "${tenant_id:-}",
    "monitoring_level": "${monitoring_level:-standard}",
    "enable_docker_overlay": ${enable_docker_overlay:-false},
    "auto_update_containers": ${auto_update_containers:-true},
    "enable_automated_backups": ${enable_automated_backups:-true}
  },
  "enrollment": {
    "status": "pending",
    "operator_url": "${saas_operator_url:-}"
  }
}
JSON
        chown "$app:$app" "$data_dir/state.json"
        chmod 600 "$data_dir/state.json"
    fi
}

# ---------------------------------------------------------------------------
# Enrollment credentials
# ---------------------------------------------------------------------------

nexora_store_enrollment_credentials() {
    local cred_dir="$data_dir/credentials"
    mkdir -p "$cred_dir"

    echo "${enrollment_token}" > "$cred_dir/enrollment-token"
    echo "${saas_operator_url}" > "$cred_dir/control-plane-url"
    echo "${tenant_id}" > "$cred_dir/tenant-id"

    chmod 700 "$cred_dir"
    chmod 600 "$cred_dir"/*
    chown -R "$app:$app" "$cred_dir"
}

# ---------------------------------------------------------------------------
# Python stack installation
# ---------------------------------------------------------------------------

nexora_install_python_stack() {
    local bundle_dir="${NEXORA_WHEEL_BUNDLE_DIR:-$install_dir/offline-bundle}"
    local wheel_dir="$bundle_dir/wheels"

    python3 -m venv "$install_dir/venv"
    if [ ! -x "$install_dir/venv/bin/pip" ]; then
        "$install_dir/venv/bin/python" -m ensurepip --upgrade
    fi

    if [ -d "$wheel_dir" ] && ls "$wheel_dir"/*.whl >/dev/null 2>&1; then
        local nexora_wheel
        nexora_wheel="$(ls "$wheel_dir"/nexora_node_agent-*.whl 2>/dev/null | head -n1)"
        [ -n "$nexora_wheel" ] || ynh_die "Offline bundle found but nexora_node_agent wheel is missing in $wheel_dir"
        ynh_print_info "Installing Nexora Node Agent from offline wheel bundle"
        "$install_dir/venv/bin/python" -m pip install --no-index --find-links "$wheel_dir" "$nexora_wheel"
    else
        "$install_dir/venv/bin/python" -m pip install --upgrade pip setuptools wheel
        "$install_dir/venv/bin/python" -m pip install "$install_dir"
    fi
}

# ---------------------------------------------------------------------------
# Permissions and runtime directories
# ---------------------------------------------------------------------------

nexora_fix_runtime_permissions() {
    mkdir -p "$data_dir"
    mkdir -p "$NEXORA_OVERLAY_DIR"
    chown -R "$app:$app" "$data_dir"
    chown -R "$app:$app" "$NEXORA_OVERLAY_DIR"
    if [ -d "$install_dir" ]; then
        chown -R "$app:$app" "$install_dir"
    fi
}

# ---------------------------------------------------------------------------
# Node agent systemd service
# ---------------------------------------------------------------------------

nexora_install_node_agent_service() {
    local service_name="${app}-node-agent"
    ynh_config_add --template="systemd-node-agent.service" \
                   --destination="/etc/systemd/system/${service_name}.service"
    systemctl daemon-reload
    systemctl enable "$service_name"
}

nexora_start_node_agent() {
    local service_name="${app}-node-agent"
    systemctl start "$service_name" || {
        ynh_print_warn "Node agent failed to start — check journalctl -u $service_name"
    }
}

nexora_stop_node_agent() {
    local service_name="${app}-node-agent"
    if systemctl is-enabled "$service_name" >/dev/null 2>&1; then
        systemctl stop "$service_name" || true
    fi
}

nexora_remove_node_agent_service() {
    local service_name="${app}-node-agent"
    if systemctl is-enabled "$service_name" >/dev/null 2>&1; then
        systemctl disable --now "$service_name" || true
    fi
    rm -f "/etc/systemd/system/${service_name}.service"
    systemctl daemon-reload || true
}

# ---------------------------------------------------------------------------
# Docker overlay management
# ---------------------------------------------------------------------------
# NOTE: The node agent alone CANNOT install Docker or overlay features.
# All overlay deployments (Docker, services, cron, nginx, systemd) are
# pushed by the SaaS control plane via HMAC-signed API commands.
# The functions below are ONLY used during uninstall for rollback.
# ---------------------------------------------------------------------------

nexora_full_overlay_rollback() {
    ynh_print_info "Running full overlay rollback — restoring pure YunoHost state..."
    if [ -f "$NEXORA_OVERLAY_MANIFEST" ]; then
        "$install_dir/venv/bin/python" -c "
from nexora_node_sdk.overlay import full_overlay_rollback
result = full_overlay_rollback()
print(f'Overlay rollback complete: {result}')
" 2>&1 || ynh_print_warn "Overlay rollback encountered errors — check logs"
    else
        ynh_print_info "No overlay manifest found — nothing to rollback"
    fi

    # Clean guard directory (HMAC secrets, tamper logs)
    local guard_dir="/opt/nexora/guard"
    if [ -d "$guard_dir" ]; then
        ynh_print_info "Removing overlay guard directory..."
        rm -rf "$guard_dir"
    fi
}

# ---------------------------------------------------------------------------
# Backup cron
# ---------------------------------------------------------------------------

nexora_install_backup_cron() {
    local cron_file="/etc/cron.d/nexora-node-backup"
    cat > "$cron_file" <<CRON
# Nexora automated PRA backup — daily at 03:00
0 3 * * * $app $install_dir/venv/bin/python -c "from nexora_node_sdk.pra import run_scheduled_backup; run_scheduled_backup()" >> /var/log/nexora-backup.log 2>&1
CRON
    chmod 644 "$cron_file"

    # Track in overlay manifest
    "$install_dir/venv/bin/python" -c "
from nexora_node_sdk.overlay import install_overlay_cron, save_manifest, load_manifest
manifest = load_manifest()
manifest = install_overlay_cron(manifest, 'nexora-node-backup', '$cron_file')
save_manifest(manifest)
" 2>&1 || true
}

nexora_remove_backup_cron() {
    rm -f /etc/cron.d/nexora-node-backup
}

# ---------------------------------------------------------------------------
# Nginx rendering — subscriber only (no scope conditionals needed)
# ---------------------------------------------------------------------------

nexora_render_subscriber_nginx() {
    local nginx_conf="$1"
    # Subscriber nginx is straightforward — no scope blocks to process
    # The template already contains only subscriber-relevant locations
    true
}

# ---------------------------------------------------------------------------
# Enrollment attempt
# ---------------------------------------------------------------------------

nexora_attempt_enrollment() {
    ynh_print_info "Attempting enrollment with SaaS operator at ${saas_operator_url}..."

    "$install_dir/venv/bin/python" -c "
import httpx, json, sys
url = '${saas_operator_url}'.rstrip('/') + '/api/v1/fleet/enroll'
token = '${enrollment_token}'
tenant = '${tenant_id}'
try:
    resp = httpx.post(url, json={
        'enrollment_token': token,
        'tenant_id': tenant,
        'agent_port': $NEXORA_AGENT_PORT,
    }, timeout=30.0)
    if resp.status_code in (200, 201, 202):
        print(f'Enrollment successful: {resp.json()}')
    else:
        print(f'Enrollment returned {resp.status_code} — will retry on next heartbeat', file=sys.stderr)
except Exception as e:
    print(f'Enrollment failed (will retry on heartbeat): {e}', file=sys.stderr)
" 2>&1 || {
        ynh_print_warn "Initial enrollment attempt failed — the agent will retry automatically via heartbeat."
    }
}
