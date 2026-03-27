from __future__ import annotations
import json
import logging
import subprocess
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(
            cmd, returncode=127, stdout="", stderr=str(exc)
        )


def _run_json(cmd: list[str]) -> Dict[str, Any]:
    proc = _run(cmd)
    if proc.returncode != 0:
        return {"_error": proc.stderr.strip() or proc.stdout.strip(), "_cmd": cmd}
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else {}
    except Exception as exc:
        logger.warning(
            "failed to parse YunoHost JSON output",
            extra={"cmd": cmd, "error": str(exc)},
        )
        return {"_raw": proc.stdout.strip(), "_cmd": cmd}


def ynh_version() -> Dict[str, Any]:
    return _run_json(["yunohost", "tools", "version", "--output-as", "json"])


def ynh_settings() -> Dict[str, Any]:
    return _run_json(["yunohost", "settings", "list", "--full", "--output-as", "json"])


def ynh_apps() -> Dict[str, Any]:
    return _run_json(["yunohost", "app", "list", "--output-as", "json"])


def ynh_domains() -> Dict[str, Any]:
    return _run_json(["yunohost", "domain", "list", "--output-as", "json"])


def ynh_certs() -> Dict[str, Any]:
    return _run_json(["yunohost", "domain", "cert", "status", "--output-as", "json"])


def ynh_services() -> Dict[str, Any]:
    return _run_json(["yunohost", "service", "status", "--output-as", "json"])


def ynh_backups() -> Dict[str, Any]:
    return _run_json(["yunohost", "backup", "list", "--output-as", "json"])


def ynh_permissions() -> Dict[str, Any]:
    return _run_json(["yunohost", "user", "permission", "list", "--output-as", "json"])


def ynh_diagnosis() -> Dict[str, Any]:
    return _run_json(["yunohost", "diagnosis", "show", "--output-as", "json"])


def ynh_app_map() -> Dict[str, Any]:
    return _run_json(["yunohost", "app", "map", "--output-as", "json"])
