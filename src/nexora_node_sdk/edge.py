"""Edge / Load balancer configuration generation."""

from __future__ import annotations

import datetime
import re
import subprocess as _sp
from pathlib import Path
from typing import Any


def generate_nginx_lb_config(
    backends: list[dict[str, Any]],
    domain: str,
    *,
    mode: str = "round_robin",
    health_check: bool = True,
) -> dict[str, Any]:
    """Generate an nginx load balancer config for a set of backends."""
    upstream_name = domain.replace(".", "_")
    lb_directive = {
        "round_robin": "",
        "least_conn": "least_conn;",
        "ip_hash": "ip_hash;",
    }.get(mode, "")

    upstream_block = [f"upstream {upstream_name} {{"]
    if lb_directive:
        upstream_block.append(f"    {lb_directive}")
    for b in backends:
        host = b.get("host", "127.0.0.1")
        port = b.get("port", 80)
        weight = b.get("weight", 1)
        backup = " backup" if b.get("backup") else ""
        upstream_block.append(f"    server {host}:{port} weight={weight}{backup};")
    upstream_block.append("}")

    server_block = [
        "server {",
        "    listen 443 ssl;",
        f"    server_name {domain};",
        f"    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;",
        f"    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;",
        "",
        "    location / {",
        f"        proxy_pass http://{upstream_name};",
        "        proxy_http_version 1.1;",
        "        proxy_set_header Host $host;",
        "        proxy_set_header X-Real-IP $remote_addr;",
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
        "        proxy_set_header X-Forwarded-Proto $scheme;",
        "    }",
    ]
    if health_check:
        server_block.extend(
            [
                "",
                "    location /health {",
                f"        proxy_pass http://{upstream_name}/api/health;",
                "    }",
            ]
        )
    server_block.append("}")

    config_text = "\n".join(upstream_block) + "\n\n" + "\n".join(server_block)

    return {
        "config": config_text,
        "domain": domain,
        "mode": mode,
        "backend_count": len(backends),
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_haproxy_config(
    backends: list[dict[str, Any]],
    frontend_name: str = "nexora_front",
    *,
    mode: str = "roundrobin",
) -> dict[str, Any]:
    """Generate a HAProxy config for a set of backends."""
    lines = [
        "global",
        "    log /dev/log local0",
        "    maxconn 4096",
        "",
        "defaults",
        "    mode http",
        "    timeout connect 5s",
        "    timeout client 30s",
        "    timeout server 30s",
        "    option httpchk GET /api/health",
        "",
        f"frontend {frontend_name}",
        "    bind *:443 ssl crt /etc/haproxy/certs/",
        "    default_backend nexora_backends",
        "",
        "backend nexora_backends",
        f"    balance {mode}",
        "    option httpchk GET /api/health",
    ]
    for i, b in enumerate(backends):
        host = b.get("host", "127.0.0.1")
        port = b.get("port", 80)
        check = " check" if b.get("check", True) else ""
        backup = " backup" if b.get("backup") else ""
        lines.append(f"    server node{i} {host}:{port}{check}{backup}")

    return {
        "config": "\n".join(lines),
        "frontend": frontend_name,
        "mode": mode,
        "backend_count": len(backends),
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_dns_failover(
    primary: dict[str, Any], secondary: dict[str, Any], domain: str
) -> dict[str, Any]:
    """Generate DNS failover configuration."""
    return {
        "domain": domain,
        "records": [
            {
                "type": "A",
                "name": domain,
                "value": primary.get("ip", ""),
                "ttl": 60,
                "priority": "primary",
            },
            {
                "type": "A",
                "name": domain,
                "value": secondary.get("ip", ""),
                "ttl": 60,
                "priority": "secondary",
            },
        ],
        "health_check": {
            "url": f"https://{domain}/api/health",
            "interval_seconds": 30,
            "timeout_seconds": 10,
            "failover_threshold": 3,
        },
        "strategy": "active_passive",
        "primary_node": primary.get("node_id", "primary"),
        "secondary_node": secondary.get("node_id", "secondary"),
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_maintenance_config(
    domain: str, message: str = "Maintenance en cours"
) -> dict[str, Any]:
    """Generate a maintenance mode config snippet."""
    nginx_snippet = f"""server {{
    listen 443 ssl;
    server_name {domain};
    return 503;
    error_page 503 @maintenance;
    location @maintenance {{
        default_type text/html;
        return 503 '<html><body><h1>{message}</h1><p>Le service sera bientôt de retour.</p></body></html>';
    }}
}}"""
    return {
        "domain": domain,
        "config": nginx_snippet,
        "message": message,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_network_map(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Generate a logical network map of the fleet."""
    node_list = []
    for n in nodes:
        inv = n.get("inventory", {})
        domains = (
            inv.get("domains", {}).get("domains", [])
            if isinstance(inv.get("domains"), dict)
            else []
        )
        node_list.append(
            {
                "node_id": n.get("node_id", "unknown"),
                "role": n.get("role", "apps"),
                "ip": n.get("ip", "unknown"),
                "domains": domains,
            }
        )

    return {
        "nodes": node_list,
        "edges": edges or [],
        "total_nodes": len(node_list),
        "timestamp": datetime.datetime.now().isoformat(),
    }


_RE_SAFE_DOMAIN = re.compile(r"^[a-z0-9.-]+$")


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


# ── Config apply ──────────────────────────────────────────────────────


def apply_nginx_lb(config_text: str, domain: str) -> dict[str, Any]:
    """Write nginx LB config to disk and reload."""
    try:
        path = _resolve_nginx_domain_dir(domain) / "nexora-loadbalancer.conf"
        path.write_text(config_text, encoding="utf-8")
        test = _sp.run(["nginx", "-t"], capture_output=True, text=True, timeout=10)
        if test.returncode != 0:
            path.unlink()
            return {
                "success": False,
                "error": f"nginx -t failed: {test.stderr}",
                "rollback": "Config removed",
            }
        _sp.run(["systemctl", "reload", "nginx"], timeout=10)
        return {"success": True, "path": str(path), "domain": domain}
    except Exception as e:
        return {"success": False, "error": str(e)}
