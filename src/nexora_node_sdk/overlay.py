"""Nexora Overlay Manager — tracks all additions on subscriber nodes.

When Nexora enrolls a YunoHost node, it installs a *non-destructive overlay*:
Docker runtime, monitoring agents, proxy configs, cron jobs, etc.  This module
maintains an inventory of every change so that **unenrollment restores the
machine to its original YunoHost-only state** (clean rollback).

IMPORTANT: The node agent alone CANNOT install features.  All deploy/install
functions are called only when the SaaS control plane sends a signed command
(HMAC-verified by overlay_guard).  This module is the execution engine;
authorization is enforced at the API layer.

Design principles:
  1. YunoHost core is NEVER modified — all additions live in the overlay.
  2. Every mutation is recorded in the overlay manifest.
  3. Rollback is idempotent and safe to run multiple times.
  4. The overlay manifest is persisted alongside the node state.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

OVERLAY_DIR = Path("/opt/nexora/overlay")
OVERLAY_MANIFEST_PATH = OVERLAY_DIR / "manifest.json"
DOCKER_COMPOSE_DIR = OVERLAY_DIR / "docker"
NGINX_SNIPPETS_DIR = OVERLAY_DIR / "nginx"
CRON_DIR = OVERLAY_DIR / "cron"
SYSTEMD_DIR = OVERLAY_DIR / "systemd"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest() -> dict[str, Any]:
    if OVERLAY_MANIFEST_PATH.exists():
        return json.loads(OVERLAY_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "version": 1,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "components": [],
        "docker_installed_by_nexora": False,
        "rollback_safe": True,
    }


def save_manifest(manifest: dict[str, Any]) -> None:
    OVERLAY_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = _utc_now()
    OVERLAY_MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _add_component(
    manifest: dict[str, Any],
    *,
    kind: str,
    name: str,
    detail: dict[str, Any] | None = None,
) -> None:
    entry = {
        "kind": kind,
        "name": name,
        "installed_at": _utc_now(),
        "detail": detail or {},
    }
    manifest.setdefault("components", []).append(entry)


def _remove_component(manifest: dict[str, Any], *, kind: str, name: str) -> bool:
    before = len(manifest.get("components", []))
    manifest["components"] = [
        c
        for c in manifest.get("components", [])
        if not (c["kind"] == kind and c["name"] == name)
    ]
    return len(manifest["components"]) < before


def _run_cmd(cmd: list[str], timeout: int = 60) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"ok": proc.returncode == 0, "out": proc.stdout.strip(), "err": proc.stderr.strip()}
    except FileNotFoundError:
        return {"ok": False, "out": "", "err": f"Command not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "out": "", "err": f"Timeout after {timeout}s"}


def docker_is_installed() -> bool:
    return _run_cmd(["docker", "version", "--format", "{{.Server.Version}}"])["ok"]


def install_docker_engine() -> dict[str, Any]:
    if docker_is_installed():
        return {"changed": False, "message": "Docker already installed"}
    result = _run_cmd(
        ["bash", "-c", "curl -fsSL https://get.docker.com | bash"],
        timeout=600,
    )
    if not result["ok"]:
        return {"changed": False, "error": result["err"]}
    _run_cmd(["systemctl", "enable", "docker"])
    _run_cmd(["systemctl", "start", "docker"])
    _run_cmd(["usermod", "-aG", "docker", "nexora"])
    manifest = load_manifest()
    manifest["docker_installed_by_nexora"] = True
    _add_component(manifest, kind="runtime", name="docker-engine", detail={
        "method": "get.docker.com", "installed_at": _utc_now(),
    })
    save_manifest(manifest)
    return {"changed": True, "message": "Docker CE installed and started"}


def uninstall_docker_engine() -> dict[str, Any]:
    manifest = load_manifest()
    if not manifest.get("docker_installed_by_nexora"):
        return {"changed": False, "message": "Docker was not installed by Nexora — skipping"}
    stop_all_overlay_containers()
    _run_cmd(["systemctl", "stop", "docker"])
    _run_cmd(["systemctl", "disable", "docker"])
    _run_cmd(["apt-get", "remove", "-y", "docker-ce", "docker-ce-cli", "containerd.io",
              "docker-buildx-plugin", "docker-compose-plugin"])
    _run_cmd(["apt-get", "autoremove", "-y"])
    manifest["docker_installed_by_nexora"] = False
    _remove_component(manifest, kind="runtime", name="docker-engine")
    save_manifest(manifest)
    return {"changed": True, "message": "Docker CE removed (was installed by Nexora)"}


def deploy_overlay_service(
    name: str,
    compose_content: str,
    *,
    nginx_snippet: str | None = None,
) -> dict[str, Any]:
    DOCKER_COMPOSE_DIR.mkdir(parents=True, exist_ok=True)
    compose_path = DOCKER_COMPOSE_DIR / f"{name}.yml"
    compose_path.write_text(compose_content, encoding="utf-8")
    result = _run_cmd(
        ["docker", "compose", "-f", str(compose_path), "up", "-d"], timeout=300,
    )
    manifest = load_manifest()
    _add_component(manifest, kind="docker-service", name=name, detail={
        "compose_path": str(compose_path), "nginx_snippet": bool(nginx_snippet),
    })
    if nginx_snippet:
        NGINX_SNIPPETS_DIR.mkdir(parents=True, exist_ok=True)
        snippet_path = NGINX_SNIPPETS_DIR / f"{name}.conf"
        snippet_path.write_text(nginx_snippet, encoding="utf-8")
        _add_component(manifest, kind="nginx-snippet", name=name, detail={
            "path": str(snippet_path),
        })
    save_manifest(manifest)
    return {
        "service": name, "deployed": result["ok"],
        "compose_path": str(compose_path),
        "error": result["err"] if not result["ok"] else None,
    }


def remove_overlay_service(name: str) -> dict[str, Any]:
    compose_path = DOCKER_COMPOSE_DIR / f"{name}.yml"
    removed = []
    if compose_path.exists():
        _run_cmd(["docker", "compose", "-f", str(compose_path), "down"], timeout=60)
        compose_path.unlink()
        removed.append(f"compose:{name}")
    snippet_path = NGINX_SNIPPETS_DIR / f"{name}.conf"
    if snippet_path.exists():
        snippet_path.unlink()
        removed.append(f"nginx:{name}")
    manifest = load_manifest()
    _remove_component(manifest, kind="docker-service", name=name)
    _remove_component(manifest, kind="nginx-snippet", name=name)
    save_manifest(manifest)
    return {"service": name, "removed": removed}


def stop_all_overlay_containers() -> dict[str, Any]:
    stopped = []
    if DOCKER_COMPOSE_DIR.exists():
        for f in DOCKER_COMPOSE_DIR.glob("*.yml"):
            _run_cmd(["docker", "compose", "-f", str(f), "down"], timeout=60)
            stopped.append(f.stem)
    return {"stopped": stopped}


def list_overlay_services() -> list[dict[str, Any]]:
    manifest = load_manifest()
    return [c for c in manifest.get("components", []) if c["kind"] == "docker-service"]


def install_overlay_cron(name: str, schedule: str, command: str) -> dict[str, Any]:
    CRON_DIR.mkdir(parents=True, exist_ok=True)
    cron_path = CRON_DIR / f"nexora-{name}"
    cron_path.write_text(f"# Nexora overlay cron: {name}\n{schedule} nexora {command}\n", encoding="utf-8")
    system_link = Path(f"/etc/cron.d/nexora-{name}")
    if not system_link.exists():
        system_link.symlink_to(cron_path)
    manifest = load_manifest()
    _add_component(manifest, kind="cron", name=name, detail={
        "schedule": schedule, "command": command, "path": str(cron_path),
    })
    save_manifest(manifest)
    return {"name": name, "installed": True, "path": str(system_link)}


def remove_overlay_cron(name: str) -> dict[str, Any]:
    system_link = Path(f"/etc/cron.d/nexora-{name}")
    cron_path = CRON_DIR / f"nexora-{name}"
    for p in (system_link, cron_path):
        if p.exists() or p.is_symlink():
            p.unlink()
    manifest = load_manifest()
    _remove_component(manifest, kind="cron", name=name)
    save_manifest(manifest)
    return {"name": name, "removed": True}


def install_overlay_systemd(name: str, unit_content: str) -> dict[str, Any]:
    SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
    local_path = SYSTEMD_DIR / f"nexora-{name}.service"
    local_path.write_text(unit_content, encoding="utf-8")
    system_path = Path(f"/etc/systemd/system/nexora-{name}.service")
    shutil.copy2(str(local_path), str(system_path))
    _run_cmd(["systemctl", "daemon-reload"])
    _run_cmd(["systemctl", "enable", f"nexora-{name}"])
    _run_cmd(["systemctl", "start", f"nexora-{name}"])
    manifest = load_manifest()
    _add_component(manifest, kind="systemd", name=name, detail={"unit": str(system_path)})
    save_manifest(manifest)
    return {"name": name, "installed": True}


def remove_overlay_systemd(name: str) -> dict[str, Any]:
    unit_name = f"nexora-{name}"
    _run_cmd(["systemctl", "stop", unit_name])
    _run_cmd(["systemctl", "disable", unit_name])
    for p in (
        Path(f"/etc/systemd/system/{unit_name}.service"),
        SYSTEMD_DIR / f"{unit_name}.service",
    ):
        if p.exists():
            p.unlink()
    _run_cmd(["systemctl", "daemon-reload"])
    manifest = load_manifest()
    _remove_component(manifest, kind="systemd", name=name)
    save_manifest(manifest)
    return {"name": name, "removed": True}


def install_overlay_nginx_snippet(name: str, content: str, domain: str) -> dict[str, Any]:
    NGINX_SNIPPETS_DIR.mkdir(parents=True, exist_ok=True)
    local_path = NGINX_SNIPPETS_DIR / f"{name}.conf"
    local_path.write_text(content, encoding="utf-8")
    system_path = Path(f"/etc/nginx/conf.d/{domain}.d/nexora-{name}.conf")
    system_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(local_path), str(system_path))
    _run_cmd(["nginx", "-t"])
    _run_cmd(["systemctl", "reload", "nginx"])
    manifest = load_manifest()
    _add_component(manifest, kind="nginx-snippet", name=name, detail={
        "path": str(system_path), "domain": domain,
    })
    save_manifest(manifest)
    return {"name": name, "installed": True, "path": str(system_path)}


def remove_overlay_nginx_snippet(name: str) -> dict[str, Any]:
    removed = []
    for conf in Path("/etc/nginx/conf.d/").rglob(f"nexora-{name}.conf"):
        conf.unlink()
        removed.append(str(conf))
    local_path = NGINX_SNIPPETS_DIR / f"{name}.conf"
    if local_path.exists():
        local_path.unlink()
        removed.append(str(local_path))
    if removed:
        _run_cmd(["nginx", "-t"])
        _run_cmd(["systemctl", "reload", "nginx"])
    manifest = load_manifest()
    _remove_component(manifest, kind="nginx-snippet", name=name)
    save_manifest(manifest)
    return {"name": name, "removed": removed}


def full_overlay_rollback() -> dict[str, Any]:
    """Remove ALL Nexora overlay components, restoring pure YunoHost state."""
    manifest = load_manifest()
    results: dict[str, list[str]] = {
        "docker_services": [], "nginx_snippets": [],
        "crons": [], "systemd_units": [], "docker_engine": [],
    }
    for comp in list(manifest.get("components", [])):
        if comp["kind"] == "docker-service":
            remove_overlay_service(comp["name"])
            results["docker_services"].append(comp["name"])
        elif comp["kind"] == "nginx-snippet":
            remove_overlay_nginx_snippet(comp["name"])
            results["nginx_snippets"].append(comp["name"])
        elif comp["kind"] == "cron":
            remove_overlay_cron(comp["name"])
            results["crons"].append(comp["name"])
        elif comp["kind"] == "systemd":
            remove_overlay_systemd(comp["name"])
            results["systemd_units"].append(comp["name"])
    docker_result = uninstall_docker_engine()
    if docker_result.get("changed"):
        results["docker_engine"].append("docker-ce")
    if OVERLAY_DIR.exists():
        shutil.rmtree(OVERLAY_DIR, ignore_errors=True)
    return {
        "rollback_complete": True, "timestamp": _utc_now(),
        "removed": results,
        "message": "All Nexora overlay components removed. YunoHost is restored to its original state.",
    }


def overlay_status() -> dict[str, Any]:
    manifest = load_manifest()
    components = manifest.get("components", [])
    by_kind: dict[str, int] = {}
    for c in components:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    return {
        "overlay_active": len(components) > 0,
        "docker_installed_by_nexora": manifest.get("docker_installed_by_nexora", False),
        "component_count": len(components),
        "components_by_kind": by_kind,
        "components": components,
        "rollback_safe": manifest.get("rollback_safe", True),
        "manifest_path": str(OVERLAY_MANIFEST_PATH),
    }
