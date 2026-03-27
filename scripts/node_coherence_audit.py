#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def read_os_release() -> dict[str, str]:
    payload: dict[str, str] = {}
    path = Path('/etc/os-release')
    if not path.exists():
        return payload
    for line in path.read_text(encoding='utf-8').splitlines():
        if '=' not in line or line.startswith('#'):
            continue
        key, value = line.split('=', 1)
        payload[key] = value.strip().strip('"')
    return payload


def dpkg_version(pkg: str) -> str | None:
    try:
        out = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', pkg], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None
    return out or None


def major(version: str | None) -> int | None:
    if not version:
        return None
    token = version.split('.', 1)[0]
    return int(token) if token.isdigit() else None


def ynh_track(version: str) -> str:
    maj = major(version)
    if maj is None:
        return 'unknown'
    if maj <= 11:
        return 'legacy'
    if maj == 12:
        return 'current'
    if maj == 13:
        return 'next'
    return 'future'


def build_report(args: argparse.Namespace) -> dict:
    osr = read_os_release()
    pkg_names = [
        'yunohost',
        'moulinette',
        'ssowat',
        'nginx',
        'python3',
        'nexora-platform',
    ]
    pkg_versions = {name: dpkg_version(name) for name in pkg_names}

    blockers: list[str] = []
    warnings: list[str] = []

    distro_id = osr.get('ID', 'unknown')
    distro_ver = osr.get('VERSION_ID', 'unknown')
    dmaj = major(distro_ver)
    if distro_id != 'debian':
        blockers.append('unsupported_distribution_non_debian')
    elif dmaj is None or dmaj < 11:
        blockers.append('unsupported_debian_major')
    elif dmaj >= 14:
        warnings.append('untested_debian_major_future')

    ynh_major = major(args.yunohost_version)
    if ynh_major is None:
        blockers.append('missing_yunohost_version')
    elif ynh_major < 11:
        blockers.append('unsupported_yunohost_major')
    elif ynh_major >= 14:
        warnings.append('untested_yunohost_major_future')

    if args.scope == 'subscriber' and args.profile != 'node-agent-only':
        blockers.append('subscriber_scope_requires_node_agent_only')

    if pkg_versions.get('yunohost') is None:
        warnings.append('yunohost_package_not_visible_via_dpkg')

    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'scope': args.scope,
        'profile': args.profile,
        'mode': args.mode,
        'host': {
            'hostname': platform.node(),
            'architecture': platform.machine(),
            'distribution_id': distro_id,
            'distribution_version': distro_ver,
        },
        'versions': {
            'yunohost_version': args.yunohost_version,
            'yunohost_track': ynh_track(args.yunohost_version),
            'packages': pkg_versions,
        },
        'status': 'blocked' if blockers else 'ok',
        'blockers': blockers,
        'warnings': warnings,
        'adaptation_hints': [
            'Align node with target scope/profile before bootstrap mutations.',
            'Validate package/version drift before enrollment and after upgrades.',
            'Use this report as preflight evidence for operator audit trails.',
        ],
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description='Node coherence audit for Nexora bootstrap')
    parser.add_argument('--scope', required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--mode', required=True)
    parser.add_argument('--yunohost-version', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()

    report = build_report(args)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    if report['status'] != 'ok':
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    print(json.dumps({'status': 'ok', 'output': str(out)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
