"""Migration tools: Docker ↔ YunoHost, import/export, conversion helpers."""

from __future__ import annotations

import datetime
from typing import Any


def docker_to_ynh_checklist(image: str, app_name: str) -> dict[str, Any]:
    """Generate a checklist for converting a Docker image to a YNH package."""
    return {
        "source_image": image,
        "target_package": f"{app_name}_ynh",
        "steps": [
            {
                "step": 1,
                "action": "Analyze Dockerfile",
                "details": f"docker pull {image} && docker inspect {image}",
            },
            {
                "step": 2,
                "action": "Identify runtime",
                "details": "Python? Node? PHP? Go binary?",
            },
            {
                "step": 3,
                "action": "Identify data storage",
                "details": "Where does the app store persistent data?",
            },
            {
                "step": 4,
                "action": "Identify ports",
                "details": "Which port(s) does the app listen on?",
            },
            {
                "step": 5,
                "action": "Identify environment vars",
                "details": "Required ENV variables for configuration",
            },
            {
                "step": 6,
                "action": "Scaffold YNH package",
                "details": f"Use ynh_pkg_scaffold {app_name}",
            },
            {
                "step": 7,
                "action": "Write install script",
                "details": "Download source, build, configure systemd service",
            },
            {
                "step": 8,
                "action": "Write nginx config",
                "details": "Reverse proxy to internal port",
            },
            {
                "step": 9,
                "action": "Handle data migration",
                "details": "Copy Docker volumes to YNH data_dir",
            },
            {
                "step": 10,
                "action": "Test with package_check",
                "details": "Full lifecycle: install, backup, restore, remove",
            },
        ],
        "estimated_effort": "2-8 hours depending on complexity",
        "timestamp": datetime.datetime.now().isoformat(),
    }


def ynh_to_docker_export(app_info: dict[str, Any]) -> dict[str, Any]:
    """Generate a Dockerfile skeleton from a YNH app info."""
    app_id = app_info.get("id", "app")
    return {
        "app_id": app_id,
        "dockerfile": """FROM debian:12-slim
RUN apt-get update && apt-get install -y python3 python3-pip nginx
WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt || true
EXPOSE 8080
CMD ["python3", "-m", "app"]
""",
        "compose_snippet": f"""  {app_id}:
    build: ./{app_id}
    container_name: nexora_{app_id}
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - {app_id}_data:/app/data
""",
        "notes": [
            "This is a skeleton — adapt to the actual app runtime",
            "Data migration: copy from /home/yunohost.app/{app_id}/",
            "Nginx reverse proxy may need adjustment",
        ],
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_migration_plan(
    source_type: str, target_type: str, apps: list[str]
) -> dict[str, Any]:
    """Generate a migration plan between deployment types."""
    valid_types = {"yunohost", "docker", "bare_metal", "external"}
    if source_type not in valid_types or target_type not in valid_types:
        return {"error": f"Valid types: {valid_types}"}

    steps: list[dict[str, str]] = [
        {
            "phase": "audit",
            "action": f"Inventory all {source_type} apps and their data",
        },
        {"phase": "backup", "action": "Create full backup of source"},
        {"phase": "prepare", "action": f"Prepare {target_type} environment"},
    ]
    for app in apps:
        steps.append(
            {"phase": "migrate", "action": f"Migrate {app}: code + data + config"}
        )
    steps.extend(
        [
            {"phase": "verify", "action": "Test all migrated apps"},
            {"phase": "dns", "action": "Update DNS records"},
            {"phase": "cutover", "action": "Switch traffic to target"},
            {"phase": "monitor", "action": "Monitor for 48h post-migration"},
            {
                "phase": "cleanup",
                "action": "Decommission source (after validation period)",
            },
        ]
    )

    return {
        "source": source_type,
        "target": target_type,
        "apps": apps,
        "steps": steps,
        "estimated_downtime": "1-4 hours (with DNS propagation)",
        "rollback_plan": "Revert DNS to source, which remains intact during validation period",
        "timestamp": datetime.datetime.now().isoformat(),
    }
