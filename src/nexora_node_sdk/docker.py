"""Docker container management alongside YunoHost apps.

Philosophy: YunoHost apps remain the preferred deployment method.
Docker is for services that have no YNH package or need isolation.
Nexora manages Docker containers through the MCP without breaking YNH.
"""

from __future__ import annotations

import datetime
import json
import subprocess
from typing import Any
from pathlib import Path


def _run(cmd: list[str], timeout: int = 30) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except FileNotFoundError:
        return {"success": False, "stdout": "", "stderr": "Docker not installed"}
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": f"Timeout after {timeout}s"}


def docker_available() -> bool:
    r = _run(["docker", "version", "--format", "{{.Server.Version}}"])
    return r["success"]


def docker_info() -> dict[str, Any]:
    r = _run(["docker", "info", "--format", "{{json .}}"])
    if not r["success"]:
        return {"available": False, "error": r["stderr"]}
    try:
        info = json.loads(r["stdout"])
        return {
            "available": True,
            "version": info.get("ServerVersion", ""),
            "containers_running": info.get("ContainersRunning", 0),
            "containers_total": info.get("Containers", 0),
            "images": info.get("Images", 0),
            "storage_driver": info.get("Driver", ""),
            "memory_total_mb": round(info.get("MemTotal", 0) / 1024 / 1024),
        }
    except json.JSONDecodeError:
        return {"available": True, "raw": r["stdout"]}


def list_containers(all_containers: bool = False) -> list[dict[str, Any]]:
    fmt = '{"id":"{{.ID}}","name":"{{.Names}}","image":"{{.Image}}","status":"{{.Status}}","ports":"{{.Ports}}","state":"{{.State}}"}'
    cmd = ["docker", "ps", f"--format={fmt}"]
    if all_containers:
        cmd.append("-a")
    r = _run(cmd)
    if not r["success"]:
        return []
    containers = []
    for line in r["stdout"].splitlines():
        if line.strip():
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return containers


def container_stats() -> list[dict[str, Any]]:
    fmt = '{"name":"{{.Name}}","cpu":"{{.CPUPerc}}","mem":"{{.MemUsage}}","mem_perc":"{{.MemPerc}}","net":"{{.NetIO}}","block":"{{.BlockIO}}"}'
    r = _run(["docker", "stats", "--no-stream", f"--format={fmt}"])
    if not r["success"]:
        return []
    stats = []
    for line in r["stdout"].splitlines():
        if line.strip():
            try:
                stats.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return stats


def container_logs(name: str, lines: int = 50) -> str:
    r = _run(["docker", "logs", "--tail", str(lines), name], timeout=10)
    return r["stdout"] or r["stderr"]


def generate_compose_file(
    services: list[dict[str, Any]], project_name: str = "nexora"
) -> str:
    """Generate a docker-compose.yml from a service list."""
    compose = {
        "version": "3.8",
        "services": {},
        "networks": {
            "nexora_net": {"driver": "bridge"},
        },
    }
    for svc in services:
        name = svc.get("name", "service")
        service_def: dict[str, Any] = {
            "image": svc.get("image", ""),
            "container_name": f"nexora_{name}",
            "restart": svc.get("restart", "unless-stopped"),
            "networks": ["nexora_net"],
        }
        if svc.get("ports"):
            service_def["ports"] = svc["ports"]
        if svc.get("volumes"):
            service_def["volumes"] = svc["volumes"]
        if svc.get("environment"):
            service_def["environment"] = svc["environment"]
        if svc.get("labels"):
            service_def["labels"] = svc["labels"]
        if svc.get("mem_limit"):
            service_def["mem_limit"] = svc["mem_limit"]
        if svc.get("cpus"):
            service_def["cpus"] = svc["cpus"]
        compose["services"][name] = service_def

    import yaml

    return yaml.dump(compose, default_flow_style=False, sort_keys=False)


def generate_nginx_proxy_for_container(
    container_name: str, domain: str, internal_port: int, *, path: str = "/"
) -> str:
    """Generate nginx reverse proxy config for a Docker container."""
    return f"""# Nexora Docker proxy: {container_name} -> {domain}{path}
location {path} {{
    proxy_pass http://127.0.0.1:{internal_port};
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}}
"""


# Pre-built Docker service templates for common needs
DOCKER_TEMPLATES = {
    "redis": {
        "image": "redis:7-alpine",
        "ports": ["127.0.0.1:6379:6379"],
        "volumes": ["nexora_redis_data:/data"],
        "mem_limit": "256m",
        "description": "Cache / message broker",
    },
    "postgres": {
        "image": "postgres:16-alpine",
        "ports": ["127.0.0.1:5432:5432"],
        "volumes": ["nexora_pg_data:/var/lib/postgresql/data"],
        "environment": {"POSTGRES_PASSWORD": "__CHANGE_ME__"},
        "mem_limit": "512m",
        "description": "PostgreSQL database",
    },
    "minio": {
        "image": "minio/minio:latest",
        "ports": ["127.0.0.1:9000:9000", "127.0.0.1:9001:9001"],
        "volumes": ["nexora_minio_data:/data"],
        "environment": {
            "MINIO_ROOT_USER": "nexora",
            "MINIO_ROOT_PASSWORD": "__CHANGE_ME__",
        },
        "command": "server /data --console-address :9001",
        "mem_limit": "512m",
        "description": "S3-compatible object storage",
    },
    "uptime-kuma": {
        "image": "louislam/uptime-kuma:1",
        "ports": ["127.0.0.1:3001:3001"],
        "volumes": ["nexora_uptime_data:/app/data"],
        "mem_limit": "256m",
        "description": "Uptime monitoring dashboard",
    },
    "n8n": {
        "image": "n8nio/n8n:latest",
        "ports": ["127.0.0.1:5678:5678"],
        "volumes": ["nexora_n8n_data:/home/node/.n8n"],
        "mem_limit": "512m",
        "description": "Workflow automation",
    },
    "grafana": {
        "image": "grafana/grafana-oss:latest",
        "ports": ["127.0.0.1:3000:3000"],
        "volumes": ["nexora_grafana_data:/var/lib/grafana"],
        "mem_limit": "256m",
        "description": "Monitoring dashboards",
    },
    "prometheus": {
        "image": "prom/prometheus:latest",
        "ports": ["127.0.0.1:9090:9090"],
        "volumes": ["nexora_prom_data:/prometheus"],
        "mem_limit": "512m",
        "description": "Metrics collection",
    },
    "plausible": {
        "image": "plausible/analytics:latest",
        "ports": ["127.0.0.1:8000:8000"],
        "mem_limit": "512m",
        "description": "Privacy-friendly web analytics",
    },
    "portainer": {
        "image": "portainer/portainer-ce:latest",
        "ports": ["127.0.0.1:9443:9443"],
        "volumes": [
            "/var/run/docker.sock:/var/run/docker.sock",
            "nexora_portainer_data:/data",
        ],
        "mem_limit": "256m",
        "description": "Docker management UI",
    },
    "watchtower": {
        "image": "containrrr/watchtower:latest",
        "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
        "environment": {
            "WATCHTOWER_CLEANUP": "true",
            "WATCHTOWER_SCHEDULE": "0 0 4 * * *",
        },
        "mem_limit": "128m",
        "description": "Auto-update Docker containers",
    },
}


def list_docker_templates() -> list[dict[str, Any]]:
    return [{"name": k, **v} for k, v in DOCKER_TEMPLATES.items()]


def get_docker_template(name: str) -> dict[str, Any] | None:
    return DOCKER_TEMPLATES.get(name)


def estimate_docker_resources(services: list[str]) -> dict[str, Any]:
    total_mem = 0
    details = []
    for svc in services:
        tpl = DOCKER_TEMPLATES.get(svc)
        if tpl:
            mem = int(tpl.get("mem_limit", "256m").rstrip("m"))
            total_mem += mem
            details.append(
                {
                    "service": svc,
                    "mem_mb": mem,
                    "description": tpl.get("description", ""),
                }
            )
        else:
            total_mem += 256
            details.append(
                {
                    "service": svc,
                    "mem_mb": 256,
                    "description": "Custom service (estimate)",
                }
            )

    return {
        "services": details,
        "total_mem_mb": total_mem,
        "recommended_ram_gb": max(2, (total_mem + 1024) // 1024 + 1),
        "timestamp": datetime.datetime.now().isoformat(),
    }


# ── Container lifecycle operations ────────────────────────────────────


def docker_pull(image: str) -> dict[str, Any]:
    r = _run(["docker", "pull", image], timeout=300)
    return {
        "action": "pull",
        "image": image,
        "success": r["success"],
        "output": r["stdout"] or r["stderr"],
    }


def docker_run(
    image: str,
    name: str,
    *,
    ports: list[str] | None = None,
    volumes: list[str] | None = None,
    environment: dict[str, str] | None = None,
    detach: bool = True,
    restart: str = "unless-stopped",
) -> dict[str, Any]:
    cmd = ["docker", "run"]
    if detach:
        cmd.append("-d")
    cmd.extend(["--name", name, "--restart", restart])
    for p in ports or []:
        cmd.extend(["-p", p])
    for v in volumes or []:
        cmd.extend(["-v", v])
    for k, val in (environment or {}).items():
        cmd.extend(["-e", f"{k}={val}"])
    cmd.append(image)
    r = _run(cmd, timeout=120)
    return {
        "action": "run",
        "name": name,
        "image": image,
        "success": r["success"],
        "container_id": r["stdout"][:12] if r["success"] else "",
        "error": r["stderr"],
    }


def docker_start(name: str) -> dict[str, Any]:
    r = _run(["docker", "start", name])
    return {
        "action": "start",
        "name": name,
        "success": r["success"],
        "error": r["stderr"],
    }


def docker_stop(name: str) -> dict[str, Any]:
    r = _run(["docker", "stop", name], timeout=30)
    return {
        "action": "stop",
        "name": name,
        "success": r["success"],
        "error": r["stderr"],
    }


def docker_remove(name: str, force: bool = False) -> dict[str, Any]:
    cmd = ["docker", "rm"]
    if force:
        cmd.append("-f")
    cmd.append(name)
    r = _run(cmd)
    return {
        "action": "remove",
        "name": name,
        "success": r["success"],
        "error": r["stderr"],
    }


def docker_compose_up(compose_path: str, detach: bool = True) -> dict[str, Any]:
    cmd = ["docker", "compose", "-f", compose_path, "up"]
    if detach:
        cmd.append("-d")
    r = _run(cmd, timeout=300)
    return {
        "action": "compose_up",
        "path": compose_path,
        "success": r["success"],
        "output": r["stdout"],
        "error": r["stderr"],
    }


def docker_compose_down(compose_path: str) -> dict[str, Any]:
    r = _run(["docker", "compose", "-f", compose_path, "down"], timeout=60)
    return {
        "action": "compose_down",
        "path": compose_path,
        "success": r["success"],
        "output": r["stdout"],
        "error": r["stderr"],
    }


def write_compose_file(
    content: str, path: str = "/opt/nexora/docker/docker-compose.yml"
) -> dict[str, Any]:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return {"written": str(p), "size_bytes": p.stat().st_size}
