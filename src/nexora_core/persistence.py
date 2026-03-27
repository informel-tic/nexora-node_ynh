"""Persistence abstraction for Nexora control-plane state."""

from __future__ import annotations

import json
import os
import sqlite3
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .state import DEFAULT_STATE, StateStore, normalize_node_record


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateRepository(Protocol):
    """Minimal persistence contract for fleet/control-plane state."""

    path: Path
    backend_name: str

    def load(self) -> dict[str, Any]: ...

    def save(self, data: dict[str, Any]) -> None: ...

    def describe(self) -> dict[str, Any]: ...

    def coherence_report(self) -> dict[str, Any]: ...


@dataclass(slots=True)
class JsonStateRepository:
    """JSON-backed implementation of the persistence contract."""

    store: StateStore
    backend_name: str = "json-file"
    backup_retention: int = 10
    schema_version: str = "ws2-v2"
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    @property
    def path(self) -> Path:
        return self.store.path

    @property
    def backup_dir(self) -> Path:
        return self.path.parent / "backups"

    @property
    def temp_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".tmp")

    @property
    def journal_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".journal")

    def _normalized_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = {**DEFAULT_STATE, **dict(data)}
        payload.pop("_state_warning", None)
        payload.pop("_state_recovery", None)
        payload.setdefault("inventory_cache", {})
        payload.setdefault("node_action_events", [])
        payload.setdefault("state_backups", [])
        payload["nodes"] = [
            normalize_node_record(node)
            for node in payload.get("nodes", [])
            if isinstance(node, dict)
        ]
        payload.setdefault("_persistence", {})
        payload["_persistence"].update(
            {
                "backend": self.backend_name,
                "schema_version": self.schema_version,
                "last_saved_at": _utc_now(),
            }
        )
        return payload

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _load_json(self, path: Path) -> dict[str, Any]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid JSON payload in {path}")
        return raw

    def _next_backup_path(self, reason: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        safe_reason = reason.replace("/", "-").replace(" ", "-")
        return self.backup_dir / f"state-{stamp}-{safe_reason}.json"

    def _list_backup_paths(self) -> list[Path]:
        if not self.backup_dir.exists():
            return []
        return sorted(self.backup_dir.glob("state-*.json"))

    def _enforce_backup_retention(self) -> None:
        backups = self._list_backup_paths()
        excess = len(backups) - self.backup_retention
        for backup in backups[: max(0, excess)]:
            backup.unlink(missing_ok=True)

    def create_backup(self, *, reason: str = "manual") -> dict[str, Any]:
        with self._lock:
            source_payload = self.load()
            backup_path = self._next_backup_path(reason)
            normalized = self._normalized_payload(source_payload)
            self._write_json(backup_path, normalized)
            self._enforce_backup_retention()
            return {
                "created": True,
                "reason": reason,
                "path": str(backup_path),
                "timestamp": _utc_now(),
            }

    def list_backups(self) -> list[dict[str, Any]]:
        return [
            {
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
            for path in self._list_backup_paths()
        ]

    def restore_backup(self, backup_path: str | Path | None = None) -> dict[str, Any]:
        with self._lock:
            selected = (
                Path(backup_path)
                if backup_path
                else (
                    self._list_backup_paths()[-1] if self._list_backup_paths() else None
                )
            )
            if selected is None or not selected.exists():
                return {"restored": False, "error": "No backup available"}
            payload = self._normalized_payload(self._load_json(selected))
            self._write_json(self.temp_path, payload)
            self.temp_path.replace(self.path)
            self.journal_path.unlink(missing_ok=True)
            return {
                "restored": True,
                "path": str(selected),
                "timestamp": _utc_now(),
            }

    def backup_policy(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "strategy": "atomic-json-with-journal-and-rotating-backups",
            "journal_path": str(self.journal_path),
            "backup_dir": str(self.backup_dir),
            "backup_retention": self.backup_retention,
            "restore_order": ["journal", "latest-backup"],
            "schema_version": self.schema_version,
        }

    def _recover_from_journal(self) -> dict[str, Any] | None:
        if not self.journal_path.exists():
            return None
        try:
            journal = self._load_json(self.journal_path)
        except (json.JSONDecodeError, OSError, ValueError):
            return {
                "recovered": False,
                "source": "journal",
                "path": str(self.journal_path),
                "timestamp": _utc_now(),
                "error": "journal_unreadable",
            }
        payload = journal.get("payload")
        if not isinstance(payload, dict):
            return {
                "recovered": False,
                "source": "journal",
                "path": str(self.journal_path),
                "timestamp": _utc_now(),
                "error": "journal_missing_payload",
            }
        normalized = self._normalized_payload(payload)
        self._write_json(self.temp_path, normalized)
        self.temp_path.replace(self.path)
        self.journal_path.unlink(missing_ok=True)
        return {
            "recovered": True,
            "source": "journal",
            "path": str(self.journal_path),
            "timestamp": _utc_now(),
        }

    def load(self) -> dict[str, Any]:
        with self._lock:
            recovery = self._recover_from_journal()
            journal_warning = (
                recovery if recovery and not recovery.get("recovered") else None
            )
            data = self.store.load()
            primary_healthy = self.path.exists() and "_state_warning" not in data
            if primary_healthy:
                normalized = self._normalized_payload(data)
                if recovery is not None and recovery.get("recovered"):
                    normalized.setdefault("_state_recovery", recovery)
                elif journal_warning is not None:
                    normalized.setdefault("_state_warning", journal_warning)
                return normalized

            backups = self._list_backup_paths()
            if backups:
                restored = self.restore_backup(backups[-1])
                if restored.get("restored"):
                    recovered = self._normalized_payload(self.store.load())
                    recovered["_state_recovery"] = {
                        "recovered": True,
                        "source": "backup",
                        "path": restored["path"],
                        "timestamp": restored["timestamp"],
                    }
                    if journal_warning is not None:
                        recovered["_state_warning"] = journal_warning
                    return recovered

            normalized = self._normalized_payload(data)
            if journal_warning is not None:
                normalized["_state_warning"] = journal_warning
            elif "_state_warning" in data:
                normalized["_state_warning"] = data["_state_warning"]
            return normalized

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            normalized = self._normalized_payload(data)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(
                self.journal_path,
                {
                    "created_at": _utc_now(),
                    "reason": "pending-save",
                    "payload": normalized,
                },
            )
            if self.path.exists():
                shutil.copy2(self.path, self._next_backup_path("pre-save"))
            self._write_json(self.temp_path, normalized)
            self.temp_path.replace(self.path)
            self.journal_path.unlink(missing_ok=True)
            self._enforce_backup_retention()

    def describe(self) -> dict[str, Any]:
        backups = self._list_backup_paths()
        return {
            "backend": self.backend_name,
            "path": str(self.path),
            "exists": self.path.exists(),
            "parent": str(self.path.parent),
            "backup_dir": str(self.backup_dir),
            "backup_count": len(backups),
            "backup_retention": self.backup_retention,
            "journal_path": str(self.journal_path),
            "journal_exists": self.journal_path.exists(),
            "schema_version": self.schema_version,
        }

    def coherence_report(self) -> dict[str, Any]:
        payload = self.load()
        return {
            "enabled": False,
            "mode": "json-only",
            "counts": {
                "nodes": len(payload.get("nodes", [])),
                "inventory_snapshots": len(payload.get("inventory_snapshots", [])),
                "security_events": len(
                    (payload.get("security_audit", {}) or {}).get("events", [])
                )
                if isinstance(payload.get("security_audit", {}), dict)
                else len(payload.get("security_audit", []))
                if isinstance(payload.get("security_audit", []), list)
                else 0,
            },
            "in_sync": True,
            "drift": {},
        }


def migrate_legacy_state_file(
    source: str | Path, destination: str | Path
) -> dict[str, Any]:
    """Normalize a legacy JSON state file into the active repository format."""

    source_path = Path(source)
    destination_path = Path(destination)
    repo = JsonStateRepository(StateStore(destination_path))

    store = StateStore(source_path)
    normalized = store.load()
    normalized.setdefault("inventory_cache", {})
    normalized.setdefault("node_action_events", [])
    normalized["nodes"] = [
        normalize_node_record(node)
        for node in normalized.get("nodes", [])
        if isinstance(node, dict)
    ]

    backup_path = None
    if destination_path.exists():
        backup = repo.create_backup(reason="pre-migration")
        backup_path = backup.get("path")
    repo.save({**DEFAULT_STATE, **normalized})
    return {
        "migrated": True,
        "source": str(source_path),
        "destination": str(destination_path),
        "backup": backup_path,
        "node_count": len(normalized.get("nodes", [])),
        "snapshot_count": len(normalized.get("inventory_snapshots", [])),
        "policy": repo.backup_policy(),
    }


def build_state_repository(path: str | Path) -> StateRepository:
    """Build the default persistence backend for the current deployment."""
    backend = (
        str(os.environ.get("NEXORA_PERSISTENCE_BACKEND", "json-file")).strip().lower()
    )
    if backend == "sql":
        sqlite_path = os.environ.get("NEXORA_SQLITE_PATH")
        db_path = (
            Path(sqlite_path) if sqlite_path else Path(path).with_suffix(".sqlite3")
        )
        return SqliteStateRepository(db_path=db_path, fallback_path=Path(path))
    return JsonStateRepository(StateStore(path))


@dataclass(slots=True)
class SqliteStateRepository:
    """SQLite-backed implementation of the persistence contract."""

    db_path: Path
    fallback_path: Path
    backend_name: str = "sql"
    schema_version: str = "ws2-sql-v1"
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )
    dual_write: bool = True

    @property
    def path(self) -> Path:
        return self.db_path

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS control_plane_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tenant_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tenant_artifacts_tenant_kind ON tenant_artifacts(tenant_id, kind)"
        )
        conn.commit()

    def _normalized_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = {**DEFAULT_STATE, **dict(data)}
        payload.pop("_state_warning", None)
        payload.pop("_state_recovery", None)
        payload.setdefault("inventory_cache", {})
        payload.setdefault("node_action_events", [])
        payload.setdefault("state_backups", [])
        payload["nodes"] = [
            normalize_node_record(node)
            for node in payload.get("nodes", [])
            if isinstance(node, dict)
        ]
        payload.setdefault("_persistence", {})
        payload["_persistence"].update(
            {
                "backend": self.backend_name,
                "schema_version": self.schema_version,
                "last_saved_at": _utc_now(),
                "db_path": str(self.db_path),
            }
        )
        return payload

    def _extract_tenant_artifacts(
        self, payload: dict[str, Any]
    ) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = []
        for snapshot in payload.get("inventory_snapshots", []):
            if not isinstance(snapshot, dict):
                continue
            tenant_id = str(snapshot.get("tenant_id") or "").strip()
            if not tenant_id:
                continue
            rows.append(
                (
                    tenant_id,
                    "inventory_snapshot",
                    json.dumps(snapshot, ensure_ascii=False),
                )
            )
        security_audit = payload.get("security_audit", {})
        if isinstance(security_audit, dict):
            security_events = security_audit.get("events", [])
        elif isinstance(security_audit, list):
            security_events = security_audit
        else:
            security_events = []
        for event in security_events:
            if not isinstance(event, dict):
                continue
            tenant_id = str(event.get("tenant_id") or "").strip()
            if not tenant_id:
                continue
            rows.append(
                (tenant_id, "security_event", json.dumps(event, ensure_ascii=False))
            )
        return rows

    def load(self) -> dict[str, Any]:
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                row = conn.execute(
                    "SELECT payload FROM control_plane_state WHERE id = 1"
                ).fetchone()
                if row is None:
                    fallback = JsonStateRepository(
                        StateStore(self.fallback_path)
                    ).load()
                    normalized = self._normalized_payload(fallback)
                    self.save(normalized)
                    normalized.setdefault("_state_recovery", {})
                    normalized["_state_recovery"].update(
                        {
                            "recovered": True,
                            "source": "json-fallback",
                            "path": str(self.fallback_path),
                            "timestamp": _utc_now(),
                        }
                    )
                    return normalized
                raw_payload = row[0]
                parsed = json.loads(raw_payload)
                if not isinstance(parsed, dict):
                    raise ValueError("Invalid SQL payload")
                return self._normalized_payload(parsed)
            finally:
                conn.close()

    def save(self, data: dict[str, Any]) -> None:
        with self._lock:
            normalized = self._normalized_payload(data)
            serialized = json.dumps(normalized, ensure_ascii=False)
            tenant_rows = self._extract_tenant_artifacts(normalized)
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                conn.execute(
                    """
                    INSERT INTO control_plane_state(id, payload, updated_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at
                    """,
                    (serialized, _utc_now()),
                )
                conn.execute("DELETE FROM tenant_artifacts")
                if tenant_rows:
                    conn.executemany(
                        "INSERT INTO tenant_artifacts(tenant_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                        [
                            (tenant_id, kind, payload_json, _utc_now())
                            for tenant_id, kind, payload_json in tenant_rows
                        ],
                    )
                conn.commit()
            finally:
                conn.close()
            if self.dual_write:
                json_repo = JsonStateRepository(StateStore(self.fallback_path))
                json_repo.save(normalized)

    def describe(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            state_row = conn.execute(
                "SELECT updated_at FROM control_plane_state WHERE id = 1"
            ).fetchone()
            tenant_count = conn.execute(
                "SELECT COUNT(*) FROM tenant_artifacts"
            ).fetchone()
            return {
                "backend": self.backend_name,
                "path": str(self.db_path),
                "exists": self.db_path.exists(),
                "schema_version": self.schema_version,
                "fallback_path": str(self.fallback_path),
                "dual_write": self.dual_write,
                # J2 flag: True when SQL is the authoritative primary (dual_write disabled)
                "j2_sql_primary": not self.dual_write,
                "last_saved_at": state_row[0] if state_row else None,
                "tenant_artifacts_count": int(tenant_count[0]) if tenant_count else 0,
            }
        finally:
            conn.close()

    def tenant_artifacts(
        self, tenant_id: str, kind: str | None = None
    ) -> list[dict[str, Any]]:
        scoped_tenant = str(tenant_id).strip()
        if not scoped_tenant:
            return []
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            if kind:
                rows = conn.execute(
                    """
                    SELECT payload, created_at
                    FROM tenant_artifacts
                    WHERE tenant_id = ? AND kind = ?
                    ORDER BY id ASC
                    """,
                    (scoped_tenant, kind),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT payload, created_at
                    FROM tenant_artifacts
                    WHERE tenant_id = ?
                    ORDER BY id ASC
                    """,
                    (scoped_tenant,),
                ).fetchall()
            parsed: list[dict[str, Any]] = []
            for raw_payload, created_at in rows:
                try:
                    payload = json.loads(raw_payload)
                except json.JSONDecodeError:
                    continue
                parsed.append({"created_at": created_at, "payload": payload})
            return parsed
        finally:
            conn.close()

    def coherence_report(self) -> dict[str, Any]:
        sql_payload = self.load()
        json_repo = JsonStateRepository(StateStore(self.fallback_path))
        json_payload = json_repo.load()

        def _security_events_count(payload: dict[str, Any]) -> int:
            audit = payload.get("security_audit", {})
            if isinstance(audit, dict):
                return len(audit.get("events", []))
            if isinstance(audit, list):
                return len(audit)
            return 0

        sql_counts = {
            "nodes": len(sql_payload.get("nodes", [])),
            "inventory_snapshots": len(sql_payload.get("inventory_snapshots", [])),
            "security_events": _security_events_count(sql_payload),
        }
        json_counts = {
            "nodes": len(json_payload.get("nodes", [])),
            "inventory_snapshots": len(json_payload.get("inventory_snapshots", [])),
            "security_events": _security_events_count(json_payload),
        }
        drift = {
            key: {"sql": sql_counts[key], "json": json_counts[key]}
            for key in sql_counts
            if sql_counts[key] != json_counts[key]
        }
        return {
            "enabled": True,
            "mode": "sql-dual-write" if self.dual_write else "sql-only",
            "in_sync": len(drift) == 0,
            "counts": {"sql": sql_counts, "json": json_counts},
            "drift": drift,
        }
