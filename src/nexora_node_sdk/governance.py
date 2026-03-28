"""Governance, compliance, risk assessment and executive reporting."""

from __future__ import annotations

import datetime
from typing import Any

from .scoring import (
    compute_security_score,
    compute_pra_score,
    compute_health_score,
    compute_compliance_score,
)


def executive_report(
    inventory: dict[str, Any],
    *,
    node_id: str = "local",
    has_pra: bool = False,
    has_monitoring: bool = True,
) -> dict[str, Any]:
    """Generate an executive summary report."""
    security = compute_security_score(inventory)
    pra = compute_pra_score(inventory)
    health = compute_health_score(inventory)
    compliance = compute_compliance_score(
        inventory, has_pra=has_pra, has_monitoring=has_monitoring
    )

    apps = (
        inventory.get("apps", {}).get("apps", [])
        if isinstance(inventory.get("apps"), dict)
        else []
    )
    domains = (
        inventory.get("domains", {}).get("domains", [])
        if isinstance(inventory.get("domains"), dict)
        else []
    )
    backups = (
        inventory.get("backups", {}).get("archives", [])
        if isinstance(inventory.get("backups"), dict)
        else []
    )

    priorities: list[str] = []
    if security["score"] < 50:
        priorities.append("Corriger les problèmes de sécurité critiques")
    if pra["score"] < 40:
        priorities.append("Mettre en place une stratégie de sauvegarde")
    if health["score"] < 60:
        priorities.append("Résoudre les problèmes de services")
    if compliance["score"] < 40:
        priorities.append("Améliorer la documentation et les pratiques")
    if not priorities:
        priorities.append("Maintenir le niveau actuel et planifier les évolutions")

    return {
        "node_id": node_id,
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "summary": {
            "apps_count": len(apps),
            "domains_count": len(domains),
            "backups_count": len(backups),
        },
        "scores": {
            "security": {"score": security["score"], "grade": security["grade"]},
            "pra": {"score": pra["score"], "grade": pra["grade"]},
            "health": {"score": health["score"], "grade": health["grade"]},
            "compliance": {
                "score": compliance["score"],
                "level": compliance["maturity_level"],
            },
        },
        "overall_score": int(
            (security["score"] + pra["score"] + health["score"] + compliance["score"])
            / 4
        ),
        "priorities": priorities,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def risk_register(inventory: dict[str, Any]) -> dict[str, Any]:
    """Generate a risk register from inventory analysis."""
    risks: list[dict[str, Any]] = []

    backups = (
        inventory.get("backups", {}).get("archives", [])
        if isinstance(inventory.get("backups"), dict)
        else []
    )
    if not backups:
        risks.append(
            {
                "id": "R001",
                "category": "continuity",
                "severity": "critical",
                "description": "Aucune sauvegarde détectée",
                "remediation": "Créer un backup immédiatement",
            }
        )

    permissions = (
        inventory.get("permissions", {}).get("permissions", {})
        if isinstance(inventory.get("permissions"), dict)
        else {}
    )
    public_count = sum(
        1
        for _, p in permissions.items()
        if isinstance(p, dict) and "visitors" in p.get("allowed", [])
    )
    if public_count > 3:
        risks.append(
            {
                "id": "R002",
                "category": "security",
                "severity": "high",
                "description": f"{public_count} apps exposées aux visiteurs",
                "remediation": "Restreindre les permissions",
            }
        )

    services = (
        inventory.get("services", {})
        if isinstance(inventory.get("services"), dict)
        else {}
    )
    down = [
        s
        for s, v in services.items()
        if isinstance(v, dict) and v.get("status") != "running"
    ]
    if down:
        risks.append(
            {
                "id": "R003",
                "category": "availability",
                "severity": "high",
                "description": f"Services arrêtés: {', '.join(down)}",
                "remediation": "Investiguer et redémarrer",
            }
        )

    certs = (
        inventory.get("certs", {}).get("certificates", {})
        if isinstance(inventory.get("certs"), dict)
        else {}
    )
    for domain, data in certs.items():
        if (
            isinstance(data, dict)
            and isinstance(data.get("validity"), (int, float))
            and data["validity"] <= 7
        ):
            risks.append(
                {
                    "id": f"R004_{domain}",
                    "category": "security",
                    "severity": "high",
                    "description": f"Certificat {domain} expire dans {data['validity']} jours",
                    "remediation": "Renouveler le certificat",
                }
            )

    risks.sort(
        key=lambda r: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(
            r["severity"], 4
        )
    )

    return {
        "risks": risks,
        "total_risks": len(risks),
        "critical_count": sum(1 for r in risks if r["severity"] == "critical"),
        "high_count": sum(1 for r in risks if r["severity"] == "high"),
        "timestamp": datetime.datetime.now().isoformat(),
    }


def change_log(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate a change log from a list of inventory snapshots."""
    from .scoring import diff_snapshots

    entries: list[dict[str, Any]] = []
    for i in range(1, len(snapshots)):
        before = snapshots[i - 1].get("inventory", {})
        after = snapshots[i].get("inventory", {})
        diff = diff_snapshots(before, after)
        if diff["changes_count"] > 0:
            entries.append(
                {
                    "from_timestamp": snapshots[i - 1].get("timestamp", ""),
                    "to_timestamp": snapshots[i].get("timestamp", ""),
                    "changes": diff["changes"],
                }
            )

    return {
        "entries": entries,
        "total_changes": sum(len(e["changes"]) for e in entries),
        "snapshot_count": len(snapshots),
        "timestamp": datetime.datetime.now().isoformat(),
    }
