"""Scoring engine for security, PRA, health, compliance and maturity."""

from __future__ import annotations

import datetime
from typing import Any


# ── Security score ────────────────────────────────────────────────────


def compute_security_score(inventory: dict[str, Any]) -> dict[str, Any]:
    score = 75
    details: list[dict[str, Any]] = []
    deductions: list[str] = []
    bonuses: list[str] = []

    permissions = (
        inventory.get("permissions", {}).get("permissions", {})
        if isinstance(inventory.get("permissions"), dict)
        else {}
    )
    public_count = 0
    for name, perm in permissions.items():
        if isinstance(perm, dict) and "visitors" in perm.get("allowed", []):
            public_count += 1
            details.append(
                {"type": "public_permission", "name": name, "severity": "warning"}
            )
    if public_count > 0:
        penalty = min(public_count * 5, 25)
        score -= penalty
        deductions.append(f"-{penalty} pts: {public_count} public permission(s)")

    services = (
        inventory.get("services", {})
        if isinstance(inventory.get("services"), dict)
        else {}
    )
    down_count = 0
    for svc, info in services.items():
        if isinstance(info, dict) and info.get("status") not in (
            "running",
            "enabled",
            None,
        ):
            down_count += 1
            details.append(
                {"type": "service_down", "name": svc, "severity": "critical"}
            )
    if down_count:
        penalty = min(down_count * 8, 30)
        score -= penalty
        deductions.append(f"-{penalty} pts: {down_count} service(s) down")

    certs = (
        inventory.get("certs", {}).get("certificates", {})
        if isinstance(inventory.get("certs"), dict)
        else {}
    )
    expired = 0
    for domain, data in certs.items():
        if isinstance(data, dict):
            validity = data.get("validity", 0)
            if isinstance(validity, (int, float)) and validity <= 0:
                expired += 1
                details.append(
                    {"type": "cert_expired", "domain": domain, "severity": "critical"}
                )
    if expired:
        score -= min(expired * 10, 20)
        deductions.append(f"-{min(expired * 10, 20)} pts: {expired} expired cert(s)")

    backups = (
        inventory.get("backups", {}).get("archives", [])
        if isinstance(inventory.get("backups"), dict)
        else []
    )
    if backups:
        bonuses.append("+5 pts: backups present")
        score += 5
    else:
        deductions.append("-10 pts: no backups")
        score -= 10

    score = max(0, min(100, score))
    grade = (
        "A"
        if score >= 85
        else "B"
        if score >= 70
        else "C"
        if score >= 50
        else "D"
        if score >= 30
        else "F"
    )

    return {
        "score": score,
        "grade": grade,
        "details": details,
        "deductions": deductions,
        "bonuses": bonuses,
        "timestamp": datetime.datetime.now().isoformat(),
    }


# ── PRA score ─────────────────────────────────────────────────────────


def compute_pra_score(inventory: dict[str, Any]) -> dict[str, Any]:
    score = 40
    details: list[str] = []

    backups = (
        inventory.get("backups", {}).get("archives", [])
        if isinstance(inventory.get("backups"), dict)
        else []
    )
    if len(backups) >= 3:
        score += 20
        details.append("+20 pts: 3+ backup archives")
    elif len(backups) >= 1:
        score += 10
        details.append(f"+10 pts: {len(backups)} backup archive(s)")
    else:
        score -= 20
        details.append("-20 pts: no backup archives")

    apps = (
        inventory.get("apps", {}).get("apps", [])
        if isinstance(inventory.get("apps"), dict)
        else []
    )
    if apps:
        score += 5
        details.append("+5 pts: apps inventory available")

    domains = (
        inventory.get("domains", {}).get("domains", [])
        if isinstance(inventory.get("domains"), dict)
        else []
    )
    if domains:
        score += 5
        details.append("+5 pts: domains inventory available")

    certs = (
        inventory.get("certs", {}).get("certificates", {})
        if isinstance(inventory.get("certs"), dict)
        else {}
    )
    if certs:
        score += 5
        details.append("+5 pts: certificates documented")

    permissions = (
        inventory.get("permissions", {})
        if isinstance(inventory.get("permissions"), dict)
        else {}
    )
    if permissions:
        score += 5
        details.append("+5 pts: permissions documented")

    services = (
        inventory.get("services", {})
        if isinstance(inventory.get("services"), dict)
        else {}
    )
    if services:
        score += 5
        details.append("+5 pts: services inventory available")

    score = max(0, min(100, score))
    return {
        "score": score,
        "grade": "A"
        if score >= 80
        else "B"
        if score >= 60
        else "C"
        if score >= 40
        else "D"
        if score >= 20
        else "F",
        "details": details,
        "backup_count": len(backups),
        "app_count": len(apps),
        "domain_count": len(domains),
        "timestamp": datetime.datetime.now().isoformat(),
    }


# ── Health score ──────────────────────────────────────────────────────


def compute_health_score(inventory: dict[str, Any]) -> dict[str, Any]:
    score = 70
    details: list[str] = []

    services = (
        inventory.get("services", {})
        if isinstance(inventory.get("services"), dict)
        else {}
    )
    total_svc = len(services)
    running = sum(
        1
        for v in services.values()
        if isinstance(v, dict) and v.get("status") == "running"
    )
    if total_svc > 0:
        ratio = running / total_svc
        bonus = int(ratio * 20)
        score += bonus
        details.append(f"+{bonus} pts: {running}/{total_svc} services running")

    backups = (
        inventory.get("backups", {}).get("archives", [])
        if isinstance(inventory.get("backups"), dict)
        else []
    )
    if backups:
        score += 5
        details.append("+5 pts: backups present")

    certs = (
        inventory.get("certs", {}).get("certificates", {})
        if isinstance(inventory.get("certs"), dict)
        else {}
    )
    if certs:
        score += 5
        details.append("+5 pts: certs documented")

    score = max(0, min(100, score))
    return {
        "score": score,
        "grade": "A"
        if score >= 85
        else "B"
        if score >= 70
        else "C"
        if score >= 50
        else "D",
        "details": details,
        "timestamp": datetime.datetime.now().isoformat(),
    }


# ── Compliance / maturity score ───────────────────────────────────────


def compute_compliance_score(
    inventory: dict[str, Any],
    *,
    has_pra: bool = False,
    has_monitoring: bool = False,
    has_fleet: bool = False,
) -> dict[str, Any]:
    score = 0
    details: list[str] = []

    # Documentation
    if inventory.get("version"):
        score += 10
        details.append("+10: version tracked")
    if inventory.get("domains"):
        score += 10
        details.append("+10: domains documented")
    if inventory.get("apps"):
        score += 10
        details.append("+10: apps inventoried")
    if inventory.get("permissions"):
        score += 10
        details.append("+10: permissions mapped")
    if inventory.get("backups"):
        score += 10
        details.append("+10: backups tracked")

    # Practices
    if has_pra:
        score += 15
        details.append("+15: PRA configured")
    if has_monitoring:
        score += 15
        details.append("+15: monitoring active")
    if has_fleet:
        score += 10
        details.append("+10: fleet management active")

    # Security baseline
    backups = (
        inventory.get("backups", {}).get("archives", [])
        if isinstance(inventory.get("backups"), dict)
        else []
    )
    if len(backups) >= 2:
        score += 10
        details.append("+10: multi-generation backups")

    score = max(0, min(100, score))
    level = (
        "enterprise"
        if score >= 80
        else "professional"
        if score >= 60
        else "standard"
        if score >= 40
        else "basic"
        if score >= 20
        else "minimal"
    )

    return {
        "score": score,
        "maturity_level": level,
        "details": details,
        "timestamp": datetime.datetime.now().isoformat(),
    }


# ── Snapshot diff ─────────────────────────────────────────────────────


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare two inventory snapshots and return a structured diff."""
    changes: list[dict[str, Any]] = []

    def _to_set(val) -> set:
        if isinstance(val, dict):
            return set(val.keys())
        if isinstance(val, list):
            items = set()
            for v in val:
                if isinstance(v, dict):
                    items.add(v.get("id", v.get("name", str(v))))
                else:
                    items.add(str(v))
            return items
        return set()

    def _list_diff(section: str, key: str):
        b_data = before.get(section, {})
        a_data = after.get(section, {})
        b_items = _to_set(b_data.get(key, [])) if isinstance(b_data, dict) else set()
        a_items = _to_set(a_data.get(key, [])) if isinstance(a_data, dict) else set()
        for item in a_items - b_items:
            changes.append({"section": section, "type": "added", "item": item})
        for item in b_items - a_items:
            changes.append({"section": section, "type": "removed", "item": item})

    _list_diff("domains", "domains")
    _list_diff("apps", "apps")
    _list_diff("backups", "archives")
    _list_diff("permissions", "permissions")

    b_services = (
        before.get("services", {}) if isinstance(before.get("services"), dict) else {}
    )
    a_services = (
        after.get("services", {}) if isinstance(after.get("services"), dict) else {}
    )
    for svc in set(list(b_services) + list(a_services)):
        b_st = (
            b_services.get(svc, {}).get("status")
            if isinstance(b_services.get(svc), dict)
            else None
        )
        a_st = (
            a_services.get(svc, {}).get("status")
            if isinstance(a_services.get(svc), dict)
            else None
        )
        if b_st != a_st:
            changes.append(
                {
                    "section": "services",
                    "type": "changed",
                    "item": svc,
                    "before": b_st,
                    "after": a_st,
                }
            )

    return {
        "changes_count": len(changes),
        "changes": changes,
        "timestamp": datetime.datetime.now().isoformat(),
    }
