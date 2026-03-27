"""Custom hooks/scripts system: pre/post deploy, events, workflows."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

HOOK_EVENTS = {
    "pre_install": "Before app installation",
    "post_install": "After app installation",
    "pre_upgrade": "Before app upgrade",
    "post_upgrade": "After app upgrade",
    "pre_backup": "Before backup creation",
    "post_backup": "After backup creation",
    "pre_restore": "Before backup restoration",
    "post_restore": "After backup restoration",
    "failover_triggered": "When failover activates",
    "failover_resolved": "When failover resolves",
    "health_check_failed": "When a health check fails",
    "score_changed": "When a score changes significantly",
    "drift_detected": "When fleet drift is detected",
    "cert_expiring": "When a certificate is about to expire",
    "disk_warning": "When disk usage exceeds threshold",
}


def list_hook_events() -> list[dict[str, Any]]:
    return [{"event": k, "description": v} for k, v in HOOK_EVENTS.items()]


def generate_hook_script(event: str, actions: list[str]) -> dict[str, Any]:
    """Generate a hook script for a specific event."""
    script_lines = [
        "#!/bin/bash",
        f"# Nexora hook: {event}",
        f"# Generated: {datetime.datetime.now().isoformat()}",
        "set -euo pipefail",
        "",
        f'echo "[$(date)] Hook {event} triggered"',
        "",
    ]
    for action in actions:
        script_lines.append(f"# Action: {action}")
        script_lines.append(f"{action}")
        script_lines.append("")

    script_lines.append(f'echo "[$(date)] Hook {event} completed"')

    return {
        "event": event,
        "script": "\n".join(script_lines),
        "path": f"/opt/nexora/hooks/{event}.sh",
        "actions": actions,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_hooks_config(hooks: dict[str, list[str]]) -> dict[str, Any]:
    """Generate a complete hooks configuration."""
    configs = {}
    for event, actions in hooks.items():
        if event in HOOK_EVENTS:
            configs[event] = generate_hook_script(event, actions)

    return {
        "hooks": configs,
        "total_hooks": len(configs),
        "hooks_dir": "/opt/nexora/hooks/",
        "timestamp": datetime.datetime.now().isoformat(),
    }


# Pre-built hook sets
HOOK_PRESETS = {
    "minimal": {
        "post_backup": ["echo 'Backup completed successfully'"],
        "health_check_failed": [
            "/opt/nexora/venv/bin/nexora-notify health_check_failed"
        ],
    },
    "standard": {
        "post_install": ["/opt/nexora/venv/bin/nexora-job daily_backup"],
        "post_backup": ["/opt/nexora/scripts/sync-backup-offsite.sh || true"],
        "health_check_failed": [
            "/opt/nexora/venv/bin/nexora-notify health_check_failed"
        ],
        "cert_expiring": ["yunohost domain cert install $DOMAIN --no-checks || true"],
        "disk_warning": ["/opt/nexora/venv/bin/nexora-notify disk_critical"],
    },
    "professional": {
        "pre_install": ["/opt/nexora/hooks/pre-deploy-checks.sh"],
        "post_install": [
            "/opt/nexora/venv/bin/nexora-job daily_backup",
            "/opt/nexora/venv/bin/nexora-notify pra_ready",
        ],
        "post_upgrade": ["/opt/nexora/venv/bin/nexora-job daily_health_check"],
        "post_backup": [
            "/opt/nexora/scripts/sync-backup-offsite.sh",
            "/opt/nexora/venv/bin/nexora-notify pra_ready",
        ],
        "failover_triggered": ["/opt/nexora/venv/bin/nexora-notify failover_triggered"],
        "health_check_failed": [
            "/opt/nexora/venv/bin/nexora-notify health_check_failed"
        ],
        "score_changed": ["/opt/nexora/venv/bin/nexora-notify security_score_drop"],
        "drift_detected": ["/opt/nexora/venv/bin/nexora-notify fleet_drift"],
        "cert_expiring": [
            "yunohost domain cert install $DOMAIN --no-checks || true",
            "/opt/nexora/venv/bin/nexora-notify cert_expiring",
        ],
        "disk_warning": [
            "/opt/nexora/scripts/backup-rotate.sh",
            "/opt/nexora/venv/bin/nexora-notify disk_critical",
        ],
    },
}


def list_hook_presets() -> list[dict[str, Any]]:
    return [
        {"name": k, "hooks_count": len(v), "events": list(v.keys())}
        for k, v in HOOK_PRESETS.items()
    ]


def install_hook(event: str, actions: list[str]) -> dict[str, Any]:
    """Generate and install a hook script to /opt/nexora/hooks/."""
    result = generate_hook_script(event, actions)
    path = Path(result["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result["script"])
    path.chmod(0o755)
    return {**result, "installed": True}


def install_hooks_preset(preset: str = "standard") -> dict[str, Any]:
    """Install all hooks from a preset."""
    hooks = HOOK_PRESETS.get(preset, HOOK_PRESETS["standard"])
    installed = []
    for event, actions in hooks.items():
        if event in HOOK_EVENTS:
            r = install_hook(event, actions)
            installed.append({"event": event, "path": r["path"]})
    return {"preset": preset, "installed": installed, "count": len(installed)}
