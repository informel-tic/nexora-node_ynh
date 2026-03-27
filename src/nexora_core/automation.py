"""Automation: scheduled job definitions, workflow templates, checklists."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any


# Pre-built automation templates
AUTOMATION_TEMPLATES = {
    "daily_backup": {
        "name": "Daily backup",
        "schedule": "0 2 * * *",
        "description": "Sauvegarde complète quotidienne à 2h",
        "actions": ["ynh_backup_create"],
        "risk": "low",
    },
    "weekly_security_audit": {
        "name": "Weekly security audit",
        "schedule": "0 6 * * 1",
        "description": "Audit de sécurité hebdomadaire le lundi à 6h",
        "actions": ["ynh_security_audit", "ynh_security_permissions_audit"],
        "risk": "low",
    },
    "daily_health_check": {
        "name": "Daily health check",
        "schedule": "0 7 * * *",
        "description": "Vérification de santé quotidienne à 7h",
        "actions": ["ynh_monitor_resources", "ynh_monitor_services", "ynh_monitor_ssl"],
        "risk": "low",
    },
    "weekly_pra_snapshot": {
        "name": "Weekly PRA snapshot",
        "schedule": "0 3 * * 0",
        "description": "Snapshot PRA hebdomadaire le dimanche à 3h",
        "actions": ["ynh_pra_snapshot", "ynh_pra_check_readiness"],
        "risk": "low",
    },
    "monthly_executive_report": {
        "name": "Monthly executive report",
        "schedule": "0 8 1 * *",
        "description": "Rapport exécutif mensuel le 1er à 8h",
        "actions": ["executive_report", "risk_register"],
        "risk": "low",
    },
    "cert_renewal_check": {
        "name": "Certificate renewal check",
        "schedule": "0 9 * * *",
        "description": "Vérification quotidienne des certificats",
        "actions": ["ynh_domain_cert_status"],
        "risk": "low",
    },
    "weekly_update_check": {
        "name": "Weekly update check",
        "schedule": "0 10 * * 3",
        "description": "Vérification des mises à jour le mercredi",
        "actions": ["ynh_system_update", "ynh_security_check_updates"],
        "risk": "low",
    },
    "backup_rotation": {
        "name": "Backup rotation",
        "schedule": "0 4 * * *",
        "description": "Rotation des sauvegardes (garder 7 dernières)",
        "actions": ["backup_rotate"],
        "risk": "moderate",
        "params": {"keep_count": 7},
    },
}


def list_automation_templates() -> list[dict[str, Any]]:
    """List all available automation templates."""
    return [{"id": k, **v} for k, v in AUTOMATION_TEMPLATES.items()]


def generate_automation_plan(profile: str = "standard") -> dict[str, Any]:
    """Generate a recommended automation plan for a given profile."""
    profiles = {
        "minimal": ["daily_backup", "cert_renewal_check"],
        "standard": [
            "daily_backup",
            "daily_health_check",
            "weekly_security_audit",
            "weekly_pra_snapshot",
            "cert_renewal_check",
        ],
        "professional": list(AUTOMATION_TEMPLATES.keys()),
    }
    selected = profiles.get(profile, profiles["standard"])
    jobs = [
        {"id": k, **AUTOMATION_TEMPLATES[k]}
        for k in selected
        if k in AUTOMATION_TEMPLATES
    ]

    return {
        "profile": profile,
        "jobs": jobs,
        "job_count": len(jobs),
        "crontab_preview": "\n".join(
            f"# {j['name']}\n{j['schedule']} /opt/nexora/venv/bin/nexora-job {j['id']}"
            for j in jobs
        ),
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_crontab(jobs: list[dict[str, Any]], user: str = "nexora") -> str:
    """Generate a crontab file from a list of job definitions."""
    lines = [
        f"# Nexora automated jobs — generated {datetime.datetime.now().isoformat()}",
        f"# User: {user}",
        "SHELL=/bin/bash",
        "PATH=/usr/bin:/usr/sbin:/opt/nexora/venv/bin",
        "",
    ]
    for job in jobs:
        lines.append(f"# {job.get('name', job.get('id', 'job'))}")
        schedule = job.get("schedule", "0 * * * *")
        job_id = job.get("id", "unknown")
        lines.append(f"{schedule} {user} /opt/nexora/venv/bin/nexora-job {job_id}")
        lines.append("")
    return "\n".join(lines)


# ── Checklists ────────────────────────────────────────────────────────

CHECKLISTS = {
    "pre_deployment": {
        "name": "Pre-deployment checklist",
        "items": [
            "Backup complet réalisé",
            "Espace disque suffisant (> 20% libre)",
            "Services critiques opérationnels",
            "Certificats SSL valides",
            "DNS configuré correctement",
            "Permissions vérifiées",
            "Tests en environnement de staging",
        ],
    },
    "post_deployment": {
        "name": "Post-deployment checklist",
        "items": [
            "Application accessible via navigateur",
            "Authentification SSO fonctionnelle",
            "Permissions correctes",
            "Logs sans erreur critique",
            "Backup post-installation réalisé",
            "Documentation mise à jour",
        ],
    },
    "incident_response": {
        "name": "Incident response checklist",
        "items": [
            "Identifier le service impacté",
            "Vérifier les logs récents",
            "Vérifier l'espace disque",
            "Vérifier la mémoire et le CPU",
            "Vérifier les certificats",
            "Tenter un redémarrage du service",
            "Vérifier après redémarrage",
            "Documenter l'incident",
            "Planifier une action corrective",
        ],
    },
    "monthly_review": {
        "name": "Monthly review checklist",
        "items": [
            "Revoir les scores de sécurité",
            "Revoir les scores PRA",
            "Vérifier la fraîcheur des backups",
            "Appliquer les mises à jour en attente",
            "Revoir les permissions publiques",
            "Vérifier les certificats (< 30 jours)",
            "Générer le rapport exécutif",
            "Planifier les actions du mois suivant",
        ],
    },
}


def list_checklists() -> list[dict[str, Any]]:
    return [{"id": k, **v} for k, v in CHECKLISTS.items()]


def get_checklist(checklist_id: str) -> dict[str, Any]:
    if checklist_id in CHECKLISTS:
        return {"id": checklist_id, **CHECKLISTS[checklist_id]}
    return {
        "error": f"Unknown checklist: {checklist_id}",
        "available": list(CHECKLISTS.keys()),
    }


def install_crontab(profile: str = "standard", user: str = "nexora") -> dict[str, Any]:
    """Generate and install the crontab to /etc/cron.d/nexora."""
    plan = generate_automation_plan(profile)
    content = generate_crontab(plan["jobs"], user)
    path = Path("/etc/cron.d/nexora")
    try:
        path.write_text(content)
        path.chmod(0o644)
        return {
            "installed": True,
            "path": str(path),
            "jobs": plan["job_count"],
            "profile": profile,
        }
    except PermissionError:
        # Fallback: write to /opt/nexora/var/
        fallback = Path("/opt/nexora/var/crontab-nexora")
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(content)
        return {
            "installed": False,
            "fallback_path": str(fallback),
            "jobs": plan["job_count"],
            "profile": profile,
            "note": "Permission denied for /etc/cron.d/. Copy manually: sudo cp "
            + str(fallback)
            + " /etc/cron.d/nexora",
        }
