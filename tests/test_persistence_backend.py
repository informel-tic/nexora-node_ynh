from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from nexora_node_sdk.orchestrator import NexoraService, _SECTION_FETCHERS
from nexora_node_sdk.persistence import JsonStateRepository, SqliteStateRepository, build_state_repository, migrate_legacy_state_file
from nexora_node_sdk.state import StateStore


class PersistenceBackendTests(unittest.TestCase):
    def test_json_state_repository_describes_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            repo = JsonStateRepository(StateStore(path))
            description = repo.describe()
            self.assertEqual(description["backend"], "json-file")
            self.assertEqual(description["path"], str(path))
            self.assertEqual(description["backup_retention"], 10)

    def test_build_state_repository_returns_json_backend(self):
        repo = build_state_repository("/tmp/nexora-state.json")
        self.assertEqual(repo.backend_name, "json-file")

    def test_build_state_repository_returns_sql_backend_when_flagged(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "NEXORA_PERSISTENCE_BACKEND": "sql",
                "NEXORA_SQLITE_PATH": str(Path(tmp) / "state.sqlite3"),
            },
            clear=False,
        ):
            repo = build_state_repository(Path(tmp) / "state.json")
            self.assertEqual(repo.backend_name, "sql")
            self.assertIsInstance(repo, SqliteStateRepository)
            self.assertTrue(str(repo.path).endswith("state.sqlite3"))

    def test_service_exposes_persistence_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            service = NexoraService(repo_root, repo_root / "var" / "state.json")
            status = service.persistence_status()
            self.assertEqual(status["backend"], "json-file")
            self.assertTrue(status["path"].endswith("state.json"))

    def test_service_exposes_sql_coherence_status_when_backend_is_sql(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "NEXORA_PERSISTENCE_BACKEND": "sql",
                "NEXORA_SQLITE_PATH": str(Path(tmp) / "state.sqlite3"),
            },
            clear=False,
        ):
            repo_root = Path(tmp)
            service = NexoraService(repo_root, repo_root / "var" / "state.json")
            state = service.state.load()
            state["nodes"] = [{"node_id": "node-a", "tenant_id": "tenant-a"}]
            service.state.save(state)

            status = service.persistence_status()

            self.assertEqual(status["backend"], "sql")
            self.assertIn("coherence", status)
            self.assertTrue(status["coherence"]["in_sync"])

    def test_repository_save_creates_rotating_backups_and_restore_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonStateRepository(StateStore(Path(tmp) / "state.json"), backup_retention=3)
            repo.save({"nodes": [{"node_id": "node-1"}]})
            repo.save({"nodes": [{"node_id": "node-2"}]})
            repo.save({"nodes": [{"node_id": "node-3"}]})

            backups = repo.list_backups()
            self.assertGreaterEqual(len(backups), 2)

            restore = repo.restore_backup(backups[0]["path"])
            restored = repo.load()
            self.assertTrue(restore["restored"])
            self.assertEqual(restored["nodes"][0]["node_id"], "node-1")

    def test_repository_recovers_from_corrupted_primary_using_latest_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonStateRepository(StateStore(Path(tmp) / "state.json"))
            repo.save({"nodes": [{"node_id": "node-ok"}]})
            repo.save({"nodes": [{"node_id": "node-new"}]})
            repo.path.write_text("{broken", encoding="utf-8")

            recovered = repo.load()

            self.assertEqual(recovered["nodes"][0]["node_id"], "node-ok")
            self.assertEqual(recovered["_state_recovery"]["source"], "backup")

    def test_repository_ignores_truncated_journal_and_falls_back_to_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonStateRepository(StateStore(Path(tmp) / "state.json"))
            repo.save({"nodes": [{"node_id": "primary-node"}]})
            repo.journal_path.write_text("{broken", encoding="utf-8")

            recovered = repo.load()

            self.assertEqual(recovered["nodes"][0]["node_id"], "primary-node")
            self.assertEqual(recovered["_state_warning"]["error"], "journal_unreadable")
            self.assertEqual(recovered["_state_warning"]["source"], "journal")

    def test_repository_save_does_not_persist_state_warning_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonStateRepository(StateStore(Path(tmp) / "state.json"))
            repo.save({
                "nodes": [{"node_id": "primary-node"}],
                "_state_warning": {"error": "journal_unreadable"},
                "_state_recovery": {"source": "backup"},
            })

            persisted = json.loads(repo.path.read_text(encoding="utf-8"))

            self.assertNotIn("_state_warning", persisted)
            self.assertNotIn("_state_recovery", persisted)
            self.assertEqual(persisted["nodes"][0]["node_id"], "primary-node")

    def test_repository_recovers_from_backup_when_primary_missing_and_journal_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonStateRepository(StateStore(Path(tmp) / "state.json"))
            repo.save({"nodes": [{"node_id": "backup-node"}]})
            repo.save({"nodes": [{"node_id": "newer-node"}]})
            repo.path.unlink()
            repo.journal_path.write_text("{broken", encoding="utf-8")

            recovered = repo.load()

            self.assertEqual(recovered["nodes"][0]["node_id"], "backup-node")
            self.assertEqual(recovered["_state_recovery"]["source"], "backup")
            self.assertEqual(recovered["_state_warning"]["error"], "journal_unreadable")

    def test_repository_recovers_from_crash_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonStateRepository(StateStore(Path(tmp) / "state.json"))
            payload = {"nodes": [{"node_id": "journal-node"}]}
            repo.journal_path.parent.mkdir(parents=True, exist_ok=True)
            repo.journal_path.write_text(json.dumps({"payload": payload}), encoding="utf-8")

            recovered = repo.load()

            self.assertEqual(recovered["nodes"][0]["node_id"], "journal-node")
            self.assertEqual(recovered["_state_recovery"]["source"], "journal")
            self.assertFalse(repo.journal_path.exists())

    def test_repository_concurrent_saves_keep_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = JsonStateRepository(StateStore(Path(tmp) / "state.json"))

            def writer(index: int) -> None:
                for iteration in range(5):
                    repo.save({"nodes": [{"node_id": f"node-{index}-{iteration}"}]})

            threads = [threading.Thread(target=writer, args=(index,)) for index in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            loaded = repo.load()
            self.assertIn("node_id", loaded["nodes"][0])
            self.assertGreaterEqual(repo.describe()["backup_count"], 1)

    def test_sql_repository_bootstraps_from_json_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fallback = root / "state.json"
            fallback.write_text(json.dumps({"nodes": [{"node_id": "node-from-json"}]}), encoding="utf-8")
            repo = SqliteStateRepository(db_path=root / "state.sqlite3", fallback_path=fallback)

            loaded = repo.load()

            self.assertEqual(loaded["nodes"][0]["node_id"], "node-from-json")
            self.assertEqual(loaded["_state_recovery"]["source"], "json-fallback")
            self.assertEqual(repo.describe()["backend"], "sql")

    def test_sql_repository_persists_tenant_artifacts_and_scopes_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = SqliteStateRepository(db_path=root / "state.sqlite3", fallback_path=root / "state.json")
            repo.save(
                {
                    "nodes": [{"node_id": "node-a", "tenant_id": "tenant-a"}],
                    "inventory_snapshots": [
                        {"tenant_id": "tenant-a", "node_id": "node-a", "kind": "inventory"},
                        {"tenant_id": "tenant-b", "node_id": "node-b", "kind": "inventory"},
                    ],
                    "security_audit": {
                        "events": [
                            {"tenant_id": "tenant-a", "event": "token-rotation"},
                            {"tenant_id": "tenant-b", "event": "token-rotation"},
                        ]
                    },
                }
            )

            tenant_a = repo.tenant_artifacts("tenant-a")
            tenant_b = repo.tenant_artifacts("tenant-b")
            tenant_a_snapshots = repo.tenant_artifacts("tenant-a", kind="inventory_snapshot")

            self.assertTrue(tenant_a)
            self.assertTrue(tenant_b)
            self.assertTrue(all(item["payload"].get("tenant_id") == "tenant-a" for item in tenant_a))
            self.assertTrue(all(item["payload"].get("tenant_id") == "tenant-b" for item in tenant_b))
            self.assertTrue(all(item["payload"].get("kind") == "inventory" for item in tenant_a_snapshots))

    def test_sql_repository_dual_write_coherence_report_is_in_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fallback = root / "state.json"
            repo = SqliteStateRepository(db_path=root / "state.sqlite3", fallback_path=fallback)
            payload = {
                "nodes": [{"node_id": "node-a", "tenant_id": "tenant-a"}],
                "inventory_snapshots": [{"tenant_id": "tenant-a", "kind": "inventory"}],
                "security_audit": {"events": [{"tenant_id": "tenant-a", "event": "rotation"}]},
            }
            repo.save(payload)

            report = repo.coherence_report()

            self.assertTrue(report["enabled"])
            self.assertEqual(report["mode"], "sql-dual-write")
            self.assertTrue(report["in_sync"])
            self.assertEqual(report["drift"], {})

    def test_sql_repository_j2_flag_false_when_dual_write_enabled(self):
        """J2 flag must be False (not yet SQL-primary) while dual_write=True."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = SqliteStateRepository(
                db_path=root / "state.sqlite3",
                fallback_path=root / "state.json",
                dual_write=True,
            )
            repo.save({"nodes": []})
            desc = repo.describe()
            self.assertIn("j2_sql_primary", desc)
            self.assertFalse(desc["j2_sql_primary"])
            self.assertTrue(desc["dual_write"])

    def test_sql_repository_j2_flag_true_when_dual_write_disabled(self):
        """J2 flag must be True (SQL-primary) once dual_write=False."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = SqliteStateRepository(
                db_path=root / "state.sqlite3",
                fallback_path=root / "state.json",
                dual_write=False,
            )
            repo.save({"nodes": []})
            desc = repo.describe()
            self.assertTrue(desc["j2_sql_primary"])
            self.assertFalse(desc["dual_write"])

    def test_sql_repository_j2_coherence_report_shows_sql_only_mode(self):
        """coherence_report() must reflect sql-only mode when dual_write=False."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Seed the fallback JSON so coherence_report can compare
            fallback = root / "state.json"
            repo_for_seed = SqliteStateRepository(
                db_path=root / "state.sqlite3",
                fallback_path=fallback,
                dual_write=True,
            )
            repo_for_seed.save({"nodes": [{"node_id": "n1", "tenant_id": "t1"}]})

            # Switch to J2 mode
            repo_j2 = SqliteStateRepository(
                db_path=root / "state.sqlite3",
                fallback_path=fallback,
                dual_write=False,
            )
            report = repo_j2.coherence_report()
            self.assertEqual(report["mode"], "sql-only")
            self.assertTrue(report["enabled"])


class PersistenceMigrationTests(unittest.TestCase):
    def test_migrate_legacy_state_file_normalizes_nodes_and_preserves_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "legacy-state.json"
            destination = root / "var" / "state.json"
            source.write_text(
                '{"nodes": [{"node_id": "node-1", "status": "healthy"}], "inventory_snapshots": [{"kind": "legacy"}]}',
                encoding="utf-8",
            )

            result = migrate_legacy_state_file(source, destination)

            migrated = StateStore(destination).load()
            self.assertTrue(result["migrated"])
            self.assertEqual(result["node_count"], 1)
            self.assertIn("inventory_cache", migrated)
            self.assertEqual(
                migrated["nodes"][0]["allowed_transitions"],
                ["degraded", "draining", "retired", "revoked"],
            )
            self.assertEqual(migrated["inventory_snapshots"][0]["kind"], "legacy")
            self.assertEqual(result["policy"]["strategy"], "atomic-json-with-journal-and-rotating-backups")

    def test_service_reuses_persisted_inventory_cache_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            state_path = repo_root / "var" / "state.json"
            calls = {"count": 0}

            def fake_apps():
                calls["count"] += 1
                return {"apps": [{"id": "nextcloud"}], "source": calls["count"]}

            original = _SECTION_FETCHERS["apps"]
            _SECTION_FETCHERS["apps"] = fake_apps
            try:
                first = NexoraService(repo_root, state_path)
                payload1 = first.inventory_slice("apps")
                self.assertEqual(calls["count"], 1)
                self.assertEqual(payload1["source"], 1)

                second = NexoraService(repo_root, state_path)
                payload2 = second.inventory_slice("apps")
                self.assertEqual(calls["count"], 1)
                self.assertEqual(payload2["source"], 1)

                second.invalidate_cache("apps")
                payload3 = second.inventory_slice("apps")
                self.assertEqual(calls["count"], 2)
                self.assertEqual(payload3["source"], 2)
            finally:
                _SECTION_FETCHERS["apps"] = original


if __name__ == "__main__":
    unittest.main()
