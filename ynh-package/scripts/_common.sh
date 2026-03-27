#!/bin/bash
source /usr/share/yunohost/helpers

# ---------------------------------------------------------------------------
# SaaS / YunoHost separation — validation and enforcement
# ---------------------------------------------------------------------------

nexora_validate_deployment_scope() {
    local scope="${deployment_scope:-operator}"
    local profile="${nexora_profile:-control-plane+node-agent}"

    # Subscriber scope MUST be node-agent-only — never allow full platform
    if [[ "$scope" == "subscriber" && "$profile" != "node-agent-only" ]]; then
        ynh_die "Subscriber deployment scope only allows profile=node-agent-only. Cannot install control-plane in subscriber scope."
    fi

    # Subscriber must provide a SaaS operator URL to connect to
    if [[ "$scope" == "subscriber" && -z "${saas_operator_url:-}" ]]; then
        ynh_die "Subscriber scope requires a SaaS operator URL (saas_operator_url). The node-agent must know which control-plane to connect to."
    fi

    # Operator scope should not set saas_operator_url (it IS the control-plane)
    if [[ "$scope" == "operator" && -n "${saas_operator_url:-}" ]]; then
        ynh_print_info "Warning: saas_operator_url is set but deployment_scope=operator. Ignoring — this machine IS the control-plane."
    fi
}

nexora_is_operator() {
    [[ "${deployment_scope:-operator}" == "operator" ]]
}

nexora_is_subscriber() {
    [[ "${deployment_scope:-operator}" == "subscriber" ]]
}

nexora_has_control_plane() {
    local profile="${nexora_profile:-control-plane+node-agent}"
    [[ "$profile" == "control-plane" || "$profile" == "control-plane+node-agent" ]]
}

nexora_has_node_agent() {
    local profile="${nexora_profile:-control-plane+node-agent}"
    [[ "$profile" == "node-agent-only" || "$profile" == "control-plane+node-agent" ]]
}

# ---------------------------------------------------------------------------
# Nginx template — apply scope-conditional blocks
# ---------------------------------------------------------------------------

nexora_render_nginx_conf() {
    local scope="${deployment_scope:-operator}"
    local hide_ynh="${hide_yunohost_admin:-true}"
    local nginx_conf="$1"

    if [[ "$scope" == "operator" ]]; then
        # Keep operator blocks, remove subscriber blocks
        sed -i '/#NEXORA_IF_OPERATOR/d; /#NEXORA_ENDIF_OPERATOR/d' "$nginx_conf"
        sed -i '/#NEXORA_IF_SUBSCRIBER/,/#NEXORA_ENDIF_SUBSCRIBER/d' "$nginx_conf"

        # Handle YunoHost admin hiding
        if [[ "$hide_ynh" == "true" || "$hide_ynh" == "1" ]]; then
            sed -i '/#NEXORA_IF_HIDE_YNH_ADMIN/d; /#NEXORA_ENDIF_HIDE_YNH_ADMIN/d' "$nginx_conf"
        else
            sed -i '/#NEXORA_IF_HIDE_YNH_ADMIN/,/#NEXORA_ENDIF_HIDE_YNH_ADMIN/d' "$nginx_conf"
        fi
    else
        # Subscriber: keep subscriber blocks, remove operator blocks
        sed -i '/#NEXORA_IF_SUBSCRIBER/d; /#NEXORA_ENDIF_SUBSCRIBER/d' "$nginx_conf"
        sed -i '/#NEXORA_IF_OPERATOR/,/#NEXORA_ENDIF_OPERATOR/d' "$nginx_conf"
    fi
}

# ---------------------------------------------------------------------------
# State initialization — scope-aware
# ---------------------------------------------------------------------------

nexora_write_default_state() {
    local scope="${deployment_scope:-operator}"
    local brand="${operator_brand_name:-Nexora}"
    local tier="${tenant_default_tier:-free}"

    mkdir -p "$data_dir"
    if [ ! -f "$data_dir/state.json" ]; then
        if nexora_is_operator; then
            cat > "$data_dir/state.json" <<JSON
{
  "identity": {
    "brand_name": "$brand",
    "console_title": "$brand Console",
    "tagline": "Orchestration souveraine pour infrastructures YunoHost professionnelles."
  },
  "deployment": {
    "scope": "$scope",
    "profile": "${nexora_profile:-control-plane+node-agent}",
    "mode": "${deployment_mode:-adopt}",
    "enrollment_mode": "${enrollment_mode:-pull}",
    "hide_yunohost_admin": ${hide_yunohost_admin:-true},
    "tenant_default_tier": "$tier"
  },
  "nodes": [],
  "branding": {
    "brand_name": "$brand",
    "accent": "#4f46e5",
    "portal_title": "$brand Console",
    "tagline": "Orchestration souveraine pour infrastructures YunoHost professionnelles.",
    "sections": ["apps", "security", "monitoring", "pra", "fleet"]
  },
  "fleet": {"mode": "single-node", "managed_nodes": []},
  "imports": [],
  "inventory_snapshots": []
}
JSON
        else
            # Subscriber state — minimal, no console/fleet management
            cat > "$data_dir/state.json" <<JSON
{
  "identity": {
    "brand_name": "$brand",
    "role": "subscriber-agent"
  },
  "deployment": {
    "scope": "subscriber",
    "profile": "node-agent-only",
    "enrollment_mode": "${enrollment_mode:-pull}",
    "saas_operator_url": "${saas_operator_url:-}"
  },
  "enrollment": {
    "status": "pending",
    "operator_url": "${saas_operator_url:-}"
  }
}
JSON
        fi
    fi
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
        nexora_wheel="$(ls "$wheel_dir"/nexora_platform-*.whl 2>/dev/null | head -n1)"
        [ -n "$nexora_wheel" ] || ynh_die "Offline bundle found but nexora_platform wheel is missing in $wheel_dir"
        ynh_print_info "Installing Nexora from offline wheel bundle: $wheel_dir"
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
    chown -R "$app:$app" "$data_dir"
    if [ -d "$install_dir" ]; then
        chown -R "$app:$app" "$install_dir"
    fi
}

nexora_generate_api_token() {
    local token_file="$data_dir/api-token"
    if [ ! -f "$token_file" ]; then
        python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$token_file"
        chmod 600 "$token_file"
        chown "$app:$app" "$token_file"
        ynh_print_info "API token generated at $token_file"
    fi
}

nexora_setup_export_dir() {
    mkdir -p /tmp/nexora-export
    chown "$app:$app" /tmp/nexora-export
}

nexora_setup_audit_log() {
    local log_dir="/var/log/yunohost-mcp-server"
    mkdir -p "$log_dir"
    chown "$app:$app" "$log_dir"
}

nexora_setup_operator_role_lock() {
    local role_dir="/etc/nexora"
    local role_file="$role_dir/api-token-roles.json"
    mkdir -p "$role_dir"
    if [ ! -f "$role_file" ]; then
        printf '{}\n' > "$role_file"
    fi
    chown root:"$app" "$role_file"
    chmod 640 "$role_file"
}

nexora_validate_yunohost_version() {
    current="$(yunohost tools version --output-as json 2>/dev/null | python3 -c 'import json,sys; raw=sys.stdin.read().strip(); data=json.loads(raw) if raw else {}; print(data.get("yunohost",{}).get("version",""))')"
    if [ -z "$current" ]; then
        current="$(yunohost --version 2>/dev/null | python3 -c 'import re,sys; raw=sys.stdin.read().strip(); m=re.search(r"(\d+\.\d+(?:\.\d+)?)", raw); print(m.group(1) if m else "")')"
    fi
    if [ -z "$current" ]; then
        current="$(dpkg-query -W -f='${Version}\n' yunohost 2>/dev/null | python3 -c 'import re,sys; raw=sys.stdin.read().strip(); m=re.search(r"(\d+\.\d+(?:\.\d+)?)", raw); print(m.group(1) if m else "")')"
    fi
    if [ -z "$current" ]; then
        ynh_die "Unable to detect YunoHost version"
    fi
    if ! result="$(
        PYTHONPATH="$install_dir/src${PYTHONPATH:+:$PYTHONPATH}" \
        python3 -m nexora_core.bootstrap assess-package-lifecycle \
            --repo-root "$install_dir" \
            --state-path "$data_dir/state.json" \
            --domain "${domain:-}" \
            --path-url "${path_url:-/nexora}" \
            --yunohost-version "$current" \
            --operation "${1:-install}" 2>/dev/null
    )"; then
        ynh_die "Unable to assess YunoHost compatibility for operation '${1:-install}'."
    fi
    if ! python3 - "$result" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
raise SystemExit(0 if payload.get("success") else 1)
PY
    then
        ynh_die "Nexora package operation '${1:-install}' blocked for YunoHost version $current."
    fi
}

nexora_abort_if_port_busy() {
    if ss -ltn 2>/dev/null | grep -q ":38120 "; then
        ynh_die "TCP port 38120 is already in use"
    fi
}

# ---------------------------------------------------------------------------
# Systemd service management — scope-aware
# ---------------------------------------------------------------------------

nexora_install_systemd_services() {
    if nexora_has_control_plane; then
        ynh_config_add_systemd
        ynh_systemctl --service="$app" --action="enable"
    fi

    if nexora_has_node_agent; then
        # Install node-agent as a separate systemd unit
        local agent_service="${app}-node-agent"
        ynh_config_add --template="systemd-node-agent.service" --destination="/etc/systemd/system/${agent_service}.service"
        systemctl daemon-reload
        systemctl enable "$agent_service"
    fi
}

nexora_start_services() {
    if nexora_has_control_plane; then
        ynh_systemctl --service="$app" --action="start"
    fi
    if nexora_has_node_agent; then
        systemctl start "${app}-node-agent" || true
    fi
}

nexora_stop_services() {
    if nexora_has_control_plane; then
        ynh_systemctl --service="$app" --action="stop" || true
    fi
    local agent_service="${app}-node-agent"
    if systemctl is-enabled "$agent_service" >/dev/null 2>&1; then
        systemctl stop "$agent_service" || true
    fi
}

nexora_restart_services() {
    if nexora_has_control_plane; then
        ynh_systemctl --service="$app" --action="restart"
    fi
    if nexora_has_node_agent; then
        systemctl restart "${app}-node-agent" || true
    fi
}
