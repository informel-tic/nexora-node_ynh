"""Compatibility matrix loading and assessment helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_CAPABILITY_DEFAULTS: dict[str, dict[str, Any]] = {
    "observe": {
        "allowed_statuses": ["tested", "supported", "experimental", "deprecated"],
        "exact_minor_required": False,
        "manual_review_statuses": ["experimental", "deprecated"],
    },
    "inventory": {
        "allowed_statuses": ["tested", "supported", "experimental", "deprecated"],
        "exact_minor_required": False,
        "manual_review_statuses": ["experimental", "deprecated"],
    },
    "diagnosis": {
        "allowed_statuses": ["tested", "supported", "experimental", "deprecated"],
        "exact_minor_required": False,
        "manual_review_statuses": ["experimental", "deprecated"],
    },
    "enroll": {
        "allowed_statuses": ["tested", "supported", "experimental"],
        "exact_minor_required": True,
        "manual_review_statuses": ["experimental"],
    },
    "bootstrap": {
        "allowed_statuses": ["tested", "supported", "experimental"],
        "exact_minor_required": True,
        "manual_review_statuses": ["experimental"],
    },
    "install_app": {
        "allowed_statuses": ["tested", "supported", "experimental"],
        "exact_minor_required": True,
        "manual_review_statuses": ["experimental"],
    },
    "upgrade_app": {
        "allowed_statuses": ["tested", "supported", "experimental"],
        "exact_minor_required": True,
        "manual_review_statuses": ["experimental"],
    },
    "deploy_blueprint": {
        "allowed_statuses": ["tested"],
        "exact_minor_required": True,
        "manual_review_statuses": ["supported", "experimental"],
    },
    "fleet_sync": {
        "allowed_statuses": ["tested", "supported", "experimental"],
        "exact_minor_required": True,
        "manual_review_statuses": ["experimental"],
    },
}

DEFAULT_MATRIX_PATH = Path(__file__).with_name("compatibility.yaml")
REPO_MATRIX_PATH = Path("compatibility.yaml")

try:
    import yaml as _yaml  # type: ignore
except Exception:  # pragma: no cover - exercised only in limited environments
    _yaml = None


def _split_inline_items(value: str) -> list[str]:
    """Split a simple inline YAML list while respecting quoted items."""

    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in value:
        if char in {'"', "'"}:
            if quote == char:
                quote = None
            elif quote is None:
                quote = char
        if char == "," and quote is None:
            items.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if current:
        items.append("".join(current).strip())
    return [item for item in items if item]


def _parse_scalar(value: str) -> Any:
    """Parse a simple YAML scalar into a Python value."""

    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in _split_inline_items(inner)]
    if text in {"true", "True"}:
        return True
    if text in {"false", "False"}:
        return False
    if text in {"null", "None", "~"}:
        return None
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        return text


def _simple_yaml_load(raw: str) -> dict[str, Any]:
    """Load a limited indentation-based YAML subset used by Nexora."""

    entries: list[tuple[int, str]] = []
    for original_line in raw.splitlines():
        if not original_line.strip() or original_line.lstrip().startswith("#"):
            continue
        indent = len(original_line) - len(original_line.lstrip(" "))
        entries.append((indent, original_line.strip()))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(entries):
            return {}, index

        is_list = entries[index][1].startswith("- ")
        if is_list:
            result_list: list[Any] = []
            while index < len(entries):
                current_indent, line = entries[index]
                if current_indent < indent:
                    break
                if current_indent != indent or not line.startswith("- "):
                    break
                value_text = line[2:].strip()
                if value_text:
                    result_list.append(_parse_scalar(value_text))
                    index += 1
                    continue
                child, index = parse_block(index + 1, indent + 2)
                result_list.append(child)
            return result_list, index

        result_dict: dict[str, Any] = {}
        while index < len(entries):
            current_indent, line = entries[index]
            if current_indent < indent:
                break
            if current_indent != indent or line.startswith("- "):
                break
            key, _, remainder = line.partition(":")
            if not _:
                raise ValueError(f"Invalid YAML line: {line}")
            key = key.strip().strip('"')
            remainder = remainder.strip()
            if remainder:
                result_dict[key] = _parse_scalar(remainder)
                index += 1
                continue
            next_index = index + 1
            if next_index < len(entries) and entries[next_index][0] > current_indent:
                child, index = parse_block(next_index, entries[next_index][0])
                result_dict[key] = child
            else:
                result_dict[key] = {}
                index += 1
        return result_dict, index

    parsed, _ = parse_block(0, entries[0][0] if entries else 0)
    return parsed if isinstance(parsed, dict) else {}


def load_compatibility_matrix(path: str | Path | None = None) -> dict[str, Any]:
    """Load the compatibility matrix from YAML or a built-in fallback parser."""

    matrix_path = Path(path) if path else DEFAULT_MATRIX_PATH
    if not matrix_path.exists():
        return {}
    raw = matrix_path.read_text(encoding="utf-8")
    if _yaml is not None:
        data = _yaml.safe_load(raw)
    else:
        data = _simple_yaml_load(raw)
    return data if isinstance(data, dict) else {}


def resolve_compatibility_matrix_path(repo_root: str | Path | None = None) -> Path:
    """Resolve the compatibility matrix path for repo and installed layouts."""

    if repo_root is not None:
        candidate = Path(repo_root) / REPO_MATRIX_PATH
        if candidate.exists():
            return candidate
    if REPO_MATRIX_PATH.exists():
        return REPO_MATRIX_PATH
    return DEFAULT_MATRIX_PATH


def _normalize_version(version: str | None) -> str:
    """Normalize an optional version string."""

    return (version or "").strip()


def _merge_capability_policy(raw: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {}
    raw = raw if isinstance(raw, dict) else {}
    for capability, defaults in _CAPABILITY_DEFAULTS.items():
        merged = dict(defaults)
        override = raw.get(capability, {})
        if isinstance(override, dict):
            merged.update(override)
        merged["allowed_statuses"] = [
            str(item).strip()
            for item in merged.get("allowed_statuses", [])
            if str(item).strip()
        ]
        merged["manual_review_statuses"] = [
            str(item).strip()
            for item in merged.get("manual_review_statuses", [])
            if str(item).strip()
        ]
        merged["exact_minor_required"] = bool(merged.get("exact_minor_required", False))
        policies[capability] = merged
    for capability, override in raw.items():
        if capability in policies or not isinstance(override, dict):
            continue
        policies[capability] = {
            "allowed_statuses": [
                str(item).strip()
                for item in override.get("allowed_statuses", [])
                if str(item).strip()
            ],
            "manual_review_statuses": [
                str(item).strip()
                for item in override.get("manual_review_statuses", [])
                if str(item).strip()
            ],
            "exact_minor_required": bool(override.get("exact_minor_required", False)),
        }
    return policies


def _capability_verdicts(
    status: str,
    version: str,
    *,
    exact_minor: str,
    exact_minor_match: bool,
    policy: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    verdicts: dict[str, dict[str, Any]] = {}
    for capability, rules in policy.items():
        allowed_statuses = set(rules.get("allowed_statuses", []))
        manual_review_statuses = set(rules.get("manual_review_statuses", []))
        exact_minor_required = bool(rules.get("exact_minor_required", False))
        allowed = (
            bool(version)
            and status in allowed_statuses
            and (not exact_minor_required or not exact_minor or exact_minor_match)
        )
        requires_manual_review = status in manual_review_statuses or (
            exact_minor_required
            and bool(exact_minor)
            and not exact_minor_match
            and status in allowed_statuses
        )
        reasons: list[str] = []
        if not version:
            reasons.append("missing_yunohost_version")
        if status == "blocked":
            reasons.append("blocked_version")
        elif status == "unknown":
            reasons.append("version_not_listed")
        elif status not in allowed_statuses:
            reasons.append(f"status_not_allowed:{status}")
        if exact_minor_required and exact_minor and not exact_minor_match:
            reasons.append("exact_minor_mismatch")
        if requires_manual_review and status in manual_review_statuses:
            reasons.append("manual_review_required")
        verdicts[capability] = {
            "allowed": allowed,
            "requires_manual_review": requires_manual_review and not allowed,
            "reasons": reasons,
            "policy": rules,
        }
    return verdicts


def assess_compatibility(
    nexora_version: str,
    yunohost_version: str | None,
    *,
    matrix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess whether a YunoHost version is allowed for a Nexora release."""

    matrix = matrix or load_compatibility_matrix()
    releases = (
        matrix.get("releases", {}) if isinstance(matrix.get("releases"), dict) else {}
    )
    release = (
        releases.get(nexora_version, {})
        if isinstance(releases.get(nexora_version), dict)
        else {}
    )
    policy = (
        release.get("pinning_policy", {})
        if isinstance(release.get("pinning_policy"), dict)
        else {}
    )
    exact_minor = str(policy.get("exact_minor", "")).strip()
    supported = list(release.get("supported_yunohost", []) or [])
    tested = list(release.get("tested_yunohost", []) or [])
    experimental = list(release.get("experimental_yunohost", []) or [])
    deprecated = list(release.get("deprecated_yunohost", []) or [])
    blocked = list(release.get("blocked_yunohost", []) or [])
    supported_prefixes = [
        str(p).strip()
        for p in release.get("supported_yunohost_prefixes", []) or []
        if str(p).strip()
    ]
    experimental_prefixes = [
        str(p).strip()
        for p in release.get("experimental_yunohost_prefixes", []) or []
        if str(p).strip()
    ]
    deprecated_prefixes = [
        str(p).strip()
        for p in release.get("deprecated_yunohost_prefixes", []) or []
        if str(p).strip()
    ]
    capability_policy = _merge_capability_policy(release.get("capabilities", {}))
    support_tiers = (
        release.get("support_tiers", {})
        if isinstance(release.get("support_tiers"), dict)
        else {}
    )
    version = _normalize_version(yunohost_version)

    status = "unknown"
    if version in blocked:
        status = "blocked"
    elif version in tested:
        status = "tested"
    elif version in supported:
        status = "supported"
    elif version in experimental:
        status = "experimental"
    elif version in deprecated:
        status = "deprecated"
    elif version:
        # Prefix/range matching for unlisted patch versions
        if any(version.startswith(p) for p in supported_prefixes):
            status = "supported"
        elif any(version.startswith(p) for p in experimental_prefixes):
            status = "experimental"
        elif any(version.startswith(p) for p in deprecated_prefixes):
            status = "deprecated"

    exact_minor_match = (
        bool(exact_minor and version.startswith(f"{exact_minor}."))
        or version == exact_minor
    )
    capability_verdicts = _capability_verdicts(
        status,
        version,
        exact_minor=exact_minor,
        exact_minor_match=exact_minor_match,
        policy=capability_policy,
    )
    bootstrap_allowed = capability_verdicts.get("bootstrap", {}).get("allowed", False)

    reasons = []
    if not version:
        reasons.append("missing_yunohost_version")
    if status == "blocked":
        reasons.append("blocked_version")
    if status == "deprecated":
        reasons.append("deprecated_version")
    if status == "experimental":
        reasons.append("experimental_version")
    if status == "observe_only":
        reasons.append("untested_minor_version")
    if exact_minor and not exact_minor_match:
        reasons.append("exact_minor_mismatch")
    if status == "unknown":
        reasons.append("version_not_listed")

    warnings = []
    manual_review_required = False
    allowed_capabilities: list[str] = []
    for capability, verdict in capability_verdicts.items():
        if verdict.get("allowed"):
            allowed_capabilities.append(capability)
        if verdict.get("requires_manual_review"):
            manual_review_required = True
            warnings.append(f"{capability}:manual_review_required")

    # Experimental versions always warrant manual review even when capabilities are permitted
    if status == "experimental" and not manual_review_required:
        manual_review_required = True
        warnings.append("experimental_version:manual_review_recommended")

    if status == "tested":
        overall_status = "production_ready"
    elif status == "supported":
        overall_status = "supported"
    elif status == "experimental":
        overall_status = (
            "observe_only" if not bootstrap_allowed else "experimental_allowed"
        )
    elif status == "deprecated":
        overall_status = "legacy_observe_only"
    elif status == "blocked":
        overall_status = "blocked"
    else:
        overall_status = "unknown"

    return {
        "nexora_version": nexora_version,
        "yunohost_version": version or None,
        "status": status,
        "support_tier": status,
        "support_tier_meta": support_tiers.get(status, {})
        if isinstance(support_tiers.get(status, {}), dict)
        else {},
        "overall_status": overall_status,
        "bootstrap_allowed": bootstrap_allowed,
        "manual_review_required": manual_review_required,
        "allowed_capabilities": sorted(allowed_capabilities),
        "capability_verdicts": capability_verdicts,
        "pinning_policy": policy,
        "supported_yunohost": supported,
        "tested_yunohost": tested,
        "experimental_yunohost": experimental,
        "deprecated_yunohost": deprecated,
        "blocked_yunohost": blocked,
        "supported_yunohost_prefixes": supported_prefixes,
        "experimental_yunohost_prefixes": experimental_prefixes,
        "deprecated_yunohost_prefixes": deprecated_prefixes,
        "reasons": reasons,
        "warnings": sorted(set(warnings)),
    }


def validate_upgrade_path(
    current_version: str | None, target_version: str | None
) -> dict[str, Any]:
    """Validate whether a YunoHost upgrade path is considered safe."""

    current = _normalize_version(current_version)
    target = _normalize_version(target_version)
    reasons: list[str] = []
    if not current or not target:
        reasons.append("missing_version")
        return {
            "allowed": False,
            "reasons": reasons,
            "current": current or None,
            "target": target or None,
        }

    def _major_minor(version: str) -> tuple[int, int]:
        parts = version.split(".")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0

    current_major, current_minor = _major_minor(current)
    target_major, target_minor = _major_minor(target)
    if target_major > current_major:
        reasons.append("major_jump_requires_manual_review")
    elif target_minor < current_minor:
        reasons.append("downgrade_not_allowed")
    return {
        "allowed": not reasons,
        "reasons": reasons,
        "current": current,
        "target": target,
    }
