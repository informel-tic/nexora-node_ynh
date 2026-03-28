"""Storage management: volumes, quotas, S3/NFS, disk monitoring."""

from __future__ import annotations

import datetime
import subprocess
from typing import Any


def _run(cmd: list[str], timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else r.stderr.strip()
    except Exception as e:
        return str(e)


def disk_usage_detailed() -> dict[str, Any]:
    """Detailed disk usage per mount point."""
    raw = _run(["df", "-hT"])
    lines = raw.strip().splitlines()
    mounts = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 7:
            mounts.append(
                {
                    "filesystem": parts[0],
                    "type": parts[1],
                    "size": parts[2],
                    "used": parts[3],
                    "available": parts[4],
                    "use_percent": parts[5],
                    "mount": parts[6],
                }
            )
    return {"mounts": mounts, "timestamp": datetime.datetime.now().isoformat()}


def top_disk_consumers(path: str = "/", count: int = 15) -> dict[str, Any]:
    """Find largest directories."""
    raw = _run(["du", "-h", "--max-depth=2", path, "--threshold=100M"], timeout=60)
    lines = sorted(
        raw.splitlines(),
        key=lambda line: line.split("\t")[0] if "\t" in line else "",
        reverse=True,
    )[:count]
    items = []
    for line in lines:
        parts = line.split("\t", 1)
        if len(parts) == 2:
            items.append({"size": parts[0].strip(), "path": parts[1].strip()})
    return {
        "consumers": items,
        "base_path": path,
        "timestamp": datetime.datetime.now().isoformat(),
    }


def yunohost_storage_map() -> dict[str, Any]:
    """Map YunoHost-specific storage usage."""
    paths = {
        "apps": "/home/yunohost.app",
        "backups": "/home/yunohost.backup",
        "mail": "/home/yunohost.multimedia",
        "data_dir": "/home/yunohost",
        "system": "/",
    }
    usage = {}
    for label, path in paths.items():
        raw = _run(["du", "-sh", path], timeout=30)
        usage[label] = raw.split("\t")[0] if "\t" in raw else "N/A"
    return {"storage_map": usage, "timestamp": datetime.datetime.now().isoformat()}


def generate_storage_policy(profile: str = "standard") -> dict[str, Any]:
    """Generate storage quotas and policies."""
    policies = {
        "minimal": {
            "backup_retention_days": 7,
            "max_backup_count": 3,
            "alert_threshold_percent": 90,
        },
        "standard": {
            "backup_retention_days": 30,
            "max_backup_count": 7,
            "alert_threshold_percent": 85,
        },
        "professional": {
            "backup_retention_days": 90,
            "max_backup_count": 14,
            "alert_threshold_percent": 80,
            "offsite_backup": True,
            "encryption": True,
        },
    }
    return {
        "profile": profile,
        "policy": policies.get(profile, policies["standard"]),
        "recommendations": [
            "Monitor disk usage daily",
            "Rotate backups according to retention policy",
            "Use separate partition for /home/yunohost.backup",
            "Consider offsite backup for professional deployments",
        ],
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_s3_backup_config(
    bucket: str, endpoint: str = "", access_key: str = "", region: str = "auto"
) -> dict[str, Any]:
    """Generate rclone/restic config for S3 backup offloading."""
    rclone_config = f"""[nexora-s3]
type = s3
provider = Other
env_auth = false
access_key_id = {access_key or "__ACCESS_KEY__"}
secret_access_key = __SECRET_KEY__
endpoint = {endpoint or "s3.amazonaws.com"}
region = {region}
"""
    backup_script = f"""#!/bin/bash
# Nexora S3 backup sync
set -euo pipefail
BACKUP_DIR="/home/yunohost.backup/archives"
rclone sync "$BACKUP_DIR" nexora-s3:{bucket}/yunohost-backups/ --progress
echo "Backup synced to S3 at $(date)"
"""
    return {
        "rclone_config": rclone_config,
        "backup_script": backup_script,
        "bucket": bucket,
        "endpoint": endpoint or "s3.amazonaws.com",
        "cron": "0 5 * * * /opt/nexora/scripts/s3-backup-sync.sh",
        "timestamp": datetime.datetime.now().isoformat(),
    }


def generate_nfs_mount_config(
    server: str, share: str, mount_point: str = "/mnt/nexora-nfs"
) -> dict[str, Any]:
    """Generate NFS mount configuration for shared storage."""
    fstab_line = (
        f"{server}:{share} {mount_point} nfs4 defaults,_netdev,soft,timeo=150 0 0"
    )
    return {
        "fstab_entry": fstab_line,
        "mount_point": mount_point,
        "server": server,
        "share": share,
        "setup_commands": [
            "apt install -y nfs-common",
            f"mkdir -p {mount_point}",
            f"echo '{fstab_line}' >> /etc/fstab",
            f"mount {mount_point}",
        ],
        "timestamp": datetime.datetime.now().isoformat(),
    }
