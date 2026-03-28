"""App failover: health checks, automatic switchover, DNS/proxy reconfiguration."""

from __future__ import annotations

import datetime
import re
import subprocess as _sp
from pathlib import Path
from typing import Any

from .edge import generate_maintenance_config


# Health check definitions
HEALTH_CHECK_STRATEGIES = {
    "http": {
        "description": "HTTP GET on /api/health or /",
        "interval_s": 30,
        "timeout_s": 10,
        "threshold": 3,
    },
    "tcp": {
        "description": "TCP connect on service port",
        "interval_s": 15,
        "timeout_s": 5,
        "threshold": 3,
    },
    "process": {
        "description": "Check systemd unit is active",
        "interval_s": 15,
        "timeout_s": 5,
        "threshold": 2,
    },
    "combined": {
        "description": "HTTP + process + disk check",
        "interval_s": 30,
        "timeout_s": 10,
        "threshold": 2,
    },
}


def generate_health_check_config(
    app_id: str, strategy: str = "http", *, url: str = "", port: int = 0
) -> dict[str, Any]:
    base = HEALTH_CHECK_STRATEGIES.get(strategy, HEALTH_CHECK_STRATEGIES["http"]).copy()
    config = {
        "app_id": app_id,
        "strategy": strategy,
        **base,
    }
    if strategy == "http":
        config["url"] = url or f"https://localhost/{app_id}/"
    if strategy == "tcp" and port:
        config["port"] = port
    return config


def generate_failover_pair(
    app_id: str, primary: dict[str, Any], secondary: dict[str, Any], domain: str
) -> dict[str, Any]:
    """Generate a failover configuration for an app across two nodes."""
    return {
        "app_id": app_id,
        "domain": domain,
        "mode": "active_passive",
        "primary": {
            "node_id": primary.get("node_id", "primary"),
            "host": primary.get("host", ""),
            "port": primary.get("port", 443),
            "status": "active",
        },
        "secondary": {
            "node_id": secondary.get("node_id", "secondary"),
            "host": secondary.get("host", ""),
            "port": secondary.get("port", 443),
            "status": "standby",
        },
        "health_check": generate_health_check_config(app_id, "combined"),
        "failover_actions": [
            {
                "step": 1,
                "action": "update_nginx_upstream",
                "description": "Switch proxy to secondary backend",
            },
            {
                "step": 2,
                "action": "update_dns_if_needed",
                "description": "Update DNS A record TTL=60",
            },
            {"step": 3, "action": "notify_admin", "description": "Send alert to admin"},
            {
                "step": 4,
                "action": "log_event",
                "description": "Record failover in audit log",
            },
        ],
        "failback_policy": "manual",
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_failover_nginx_config(
    app_id: str, primary_host: str, secondary_host: str, domain: str
) -> str:
    """Generate nginx upstream with failover."""
    upstream = app_id.replace("-", "_")
    return f"""# Failover upstream for {app_id}
upstream {upstream}_backend {{
    server {primary_host} max_fails=3 fail_timeout=30s;
    server {secondary_host} backup;
}}

server {{
    listen 443 ssl;
    server_name {domain};

    location / {{
        proxy_pass http://{upstream}_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_next_upstream error timeout http_502 http_503 http_504;
        proxy_next_upstream_timeout 10s;
        proxy_next_upstream_tries 2;
    }}
}}
"""


def generate_failover_plan(
    apps: list[dict[str, Any]], nodes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Generate a complete failover plan for critical apps."""
    if len(nodes) < 2:
        return {
            "error": "Need at least 2 nodes for failover",
            "nodes_count": len(nodes),
        }

    primary = nodes[0]
    secondary = nodes[1]
    pairs = []

    for app in apps:
        app_id = app.get("id", app.get("app_id", "unknown"))
        domain = app.get("domain", "")
        critical = app.get("critical", False)
        if critical or app.get("failover", False):
            pairs.append(generate_failover_pair(app_id, primary, secondary, domain))

    return {
        "failover_pairs": pairs,
        "total_protected_apps": len(pairs),
        "primary_node": primary.get("node_id"),
        "secondary_node": secondary.get("node_id"),
        "strategy": "active_passive",
        "recommended_checks": [
            "Test failover monthly",
            "Verify secondary node has same apps installed",
            "Ensure backups are synced to secondary",
            "Monitor DNS TTL (keep at 60s for fast failover)",
        ],
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_keepalived_config(
    vip: str, primary_host: str, secondary_host: str, interface: str = "eth0"
) -> str:
    """Generate keepalived config for IP failover."""
    return f"""# Keepalived failover config — generated by Nexora
# Install: apt install keepalived
# Primary node config:

vrrp_script chk_nexora {{
    script "/usr/bin/curl -sf http://127.0.0.1:38120/api/health || exit 1"
    interval 5
    weight -20
    fall 3
    rise 2
}}

vrrp_instance NEXORA_VIP {{
    state MASTER
    interface {interface}
    virtual_router_id 51
    priority 100
    advert_int 1

    virtual_ipaddress {{
        {vip}
    }}

    track_script {{
        chk_nexora
    }}
}}

# --- Secondary node: same config with state BACKUP and priority 90 ---
"""


def list_health_check_strategies() -> list[dict[str, Any]]:
    return [{"strategy": k, **v} for k, v in HEALTH_CHECK_STRATEGIES.items()]


_RE_SAFE_DOMAIN = re.compile(r"^[a-z0-9.-]+$")
_RE_SAFE_APP_ID = re.compile(r"^[a-zA-Z0-9._-]+$")


def _resolve_nginx_domain_dir(domain: str) -> Path:
    normalized = domain.strip().lower()
    if not _RE_SAFE_DOMAIN.fullmatch(normalized):
        raise ValueError(f"Invalid domain for nginx apply: {domain!r}")
    path = Path(f"/etc/nginx/conf.d/{normalized}.d")
    if not path.exists():
        raise FileNotFoundError(
            f"Refusing to create a new nginx include directory outside YunoHost-managed scope: {path}"
        )
    return path


# ── Execution ─────────────────────────────────────────────────────────


def apply_failover_nginx(
    app_id: str, primary_host: str, secondary_host: str, domain: str
) -> dict[str, Any]:
    """Write failover nginx config and reload."""
    if not _RE_SAFE_APP_ID.fullmatch(app_id):
        return {
            "success": False,
            "error": f"Invalid app_id for nginx apply: {app_id!r}",
        }
    config = generate_failover_nginx_config(
        app_id, primary_host, secondary_host, domain
    )
    try:
        path = _resolve_nginx_domain_dir(domain) / f"nexora-failover-{app_id}.conf"
        path.write_text(config, encoding="utf-8")
        # Test config
        test = _sp.run(["nginx", "-t"], capture_output=True, text=True, timeout=10)
        if test.returncode != 0:
            path.unlink()  # Remove bad config
            return {
                "success": False,
                "error": f"nginx -t failed: {test.stderr}",
                "rollback": "Config removed",
            }
        # Reload
        _sp.run(["systemctl", "reload", "nginx"], timeout=10)
        return {"success": True, "path": str(path), "domain": domain, "app_id": app_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def apply_maintenance_mode(
    domain: str, message: str = "Maintenance en cours"
) -> dict[str, Any]:
    """Write and apply maintenance mode config."""
    config = generate_maintenance_config(domain, message)
    try:
        path = _resolve_nginx_domain_dir(domain) / "nexora-maintenance.conf"
        path.write_text(config["config"], encoding="utf-8")
        _sp.run(["systemctl", "reload", "nginx"], timeout=10)
        return {"success": True, "path": str(path), "domain": domain}
    except Exception as e:
        return {"success": False, "error": str(e)}


def remove_maintenance_mode(domain: str) -> dict[str, Any]:
    """Remove maintenance mode."""
    try:
        path = _resolve_nginx_domain_dir(domain) / "nexora-maintenance.conf"
        if path.exists():
            path.unlink()
        _sp.run(["systemctl", "reload", "nginx"], timeout=10)
        return {"success": True, "domain": domain}
    except Exception as e:
        return {"success": False, "error": str(e)}
