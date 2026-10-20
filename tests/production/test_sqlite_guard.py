"""Isolated deployment guard tests: no canonical paths, providers or app imports."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("sqlite_guard", ROOT / "scripts/production/sqlite_guard.py")
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="marketing-os-isolated-", dir=os.environ.get("MARKETINGOS_TEST_TEMP"))
        self.root = Path(self.tmp.name).resolve()
        self.db = self.root / "source.db"
        self.conn = sqlite3.connect(self.db)
        self.conn.executescript("""
            CREATE TABLE alembic_version(version_num TEXT NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version VALUES ('approved');
            CREATE TABLE products(id TEXT PRIMARY KEY, value BLOB, count INTEGER);
            CREATE INDEX ix_products_count ON products(count);
            INSERT INTO products VALUES ('one', x'0001FF', 2);
            INSERT INTO products VALUES ('two', NULL, 3);
        """)
        self.conn.commit(); self.conn.close()
        self.contract = {"schema_sha256": guard.inspect(self.db, "approved")["schema_sha256"],
                         "required_tables": ["products", "alembic_version"]}

    def tearDown(self):
        self.tmp.cleanup()

    def change(self, sql):
        c = sqlite3.connect(self.db)
        try:
            c.executescript(sql); c.commit()
        finally:
            c.close()

    def test_inspection_is_byte_preserving_and_no_sidecars(self):
        before = guard.sha256(self.db)
        result = guard.inspect(self.db, "approved", self.contract)
        self.assertEqual(result["quick_check"], "ok")
        self.assertEqual(result["row_counts"]["products"], 2)
        self.assertEqual(before, guard.sha256(self.db))
        self.assertFalse(Path(str(self.db) + "-wal").exists())
        self.assertFalse(Path(str(self.db) + "-shm").exists())

    def test_missing_database_not_created(self):
        p = self.root / "missing.db"
        with self.assertRaises(FileNotFoundError): guard.inspect(p, "approved")
        self.assertFalse(p.exists())

    def test_relative_path_refused(self):
        with self.assertRaises(ValueError): guard.inspect(Path("relative.db"), "approved")

    def test_wrong_revision_refused(self):
        with self.assertRaises(ValueError): guard.inspect(self.db, "wrong", self.contract)

    def test_multiple_revision_rows_refused(self):
        self.change("INSERT INTO alembic_version VALUES ('other');")
        with self.assertRaises(ValueError): guard.inspect(self.db, "approved")

    def test_empty_revision_refused(self):
        self.change("DELETE FROM alembic_version;")
        with self.assertRaises(ValueError): guard.inspect(self.db, "approved")

    def test_schema_column_drift_refused(self):
        self.change("ALTER TABLE products ADD COLUMN unexpected TEXT;")
        with self.assertRaises(ValueError): guard.inspect(self.db, "approved", self.contract)

    def test_schema_index_drift_refused(self):
        self.change("DROP INDEX ix_products_count;")
        with self.assertRaises(ValueError): guard.inspect(self.db, "approved", self.contract)

    def test_prerequisite_refused(self):
        contract = {**self.contract, "required_tables": ["absent"]}
        with self.assertRaises(ValueError): guard.inspect(self.db, "approved", contract)

    def test_corrupt_database_refused(self):
        self.db.write_bytes(b"not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError): guard.inspect(self.db, "approved")

    def test_backup_matches_rows_schema_bytes_and_source_unchanged(self):
        before = guard.sha256(self.db)
        dest = self.root / "backup.db"
        result = guard.backup(self.db, dest, "approved", self.contract)
        self.assertTrue(result["verified"])
        self.assertEqual(guard.inspect(self.db, "approved"), guard.inspect(dest, "approved"))
        self.assertEqual(result["sha256"], guard.sha256(dest))
        self.assertEqual(before, guard.sha256(self.db))

    def test_backup_will_not_overwrite(self):
        p = self.root / "existing.db"; p.write_bytes(b"preserve")
        with self.assertRaises(ValueError): guard.backup(self.db, p, "approved", self.contract)
        self.assertEqual(p.read_bytes(), b"preserve")

    def test_backup_source_collision(self):
        with self.assertRaises(ValueError): guard.backup(self.db, self.db, "approved", self.contract)

    def test_backup_guard_failure_creates_nothing(self):
        p = self.root / "not-created.db"
        with self.assertRaises(ValueError): guard.backup(self.db, p, "wrong", self.contract)
        self.assertFalse(p.exists())

    def test_backup_missing_parent_not_created(self):
        p = self.root / "absent" / "backup.db"
        with self.assertRaises(FileNotFoundError): guard.backup(self.db, p, "approved", self.contract)
        self.assertFalse(p.parent.exists())

    def test_failed_backup_verification_preserves_evidence(self):
        before = guard.inspect(self.db, "approved", self.contract)
        altered = {**before, "row_counts": {"products": 99}}
        dest = self.root / "retained-failed-backup.db"
        with patch.object(guard, "inspect", side_effect=[before, before, altered]):
            with self.assertRaises(ValueError): guard.backup(self.db, dest, "approved", self.contract)
        self.assertTrue(dest.exists())
        self.assertEqual(guard.inspect(dest, "approved")["quick_check"], "ok")

    def test_live_wal_without_shm_refused(self):
        Path(str(self.db) + "-wal").write_bytes(b"unverified WAL")
        with self.assertRaises(ValueError): guard.inspect(self.db, "approved")
        self.assertFalse(Path(str(self.db) + "-shm").exists())

    def test_data_digest_detects_same_count_mutation(self):
        a = guard.inspect(self.db, "approved")
        self.change("UPDATE products SET count=99 WHERE id='one';")
        b = guard.inspect(self.db, "approved")
        self.assertEqual(a["row_counts"], b["row_counts"])
        self.assertNotEqual(a["data_sha256"], b["data_sha256"])

    def test_migration_preserves_old_columns_while_adding_new(self):
        reference = self.root / "before.db"
        guard.backup(self.db, reference, "approved", self.contract)
        self.change("ALTER TABLE products ADD COLUMN extra TEXT DEFAULT 'new'; CREATE TABLE new_table(id TEXT);")
        self.assertTrue(guard.compare_preserved(reference, self.db)["preserved"])
        self.change("UPDATE products SET count=88 WHERE id='one';")
        with self.assertRaises(ValueError): guard.compare_preserved(reference, self.db)

    def test_migration_removed_table_refused(self):
        reference = self.root / "before.db"
        guard.backup(self.db, reference, "approved", self.contract)
        self.change("DROP TABLE products;")
        with self.assertRaises(ValueError): guard.compare_preserved(reference, self.db)

    def test_effective_settings_override_must_match(self):
        self.change("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT); INSERT INTO settings VALUES ('output_root','{\"v\":\"approved\"}');")
        contract = {"schema_sha256": guard.inspect(self.db, "approved")["schema_sha256"], "expected_settings": {"output_root": "approved"}}
        self.assertEqual(guard.inspect(self.db, "approved", contract)["quick_check"], "ok")
        contract["expected_settings"]["output_root"] = "wrong"
        with self.assertRaises(ValueError): guard.inspect(self.db, "approved", contract)

    def test_live_wal_reads_uncheckpointed_data(self):
        c = sqlite3.connect(self.db)
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("INSERT INTO products VALUES ('wal',NULL,4)"); c.commit()
            self.assertEqual(guard.inspect(self.db, "approved")["row_counts"]["products"], 3)
        finally: c.close()

    def test_retention_union_preserves_buckets(self):
        base = datetime(2026, 10, 20, tzinfo=timezone.utc)
        rows = [{"utc": (base-timedelta(days=i)).isoformat(), "backup": str(i), "verified": True}
                for i in range(450)]
        candidates = guard.retention_candidates(rows)
        keep = set(str(i) for i in range(450)) - set(candidates)
        self.assertTrue(set(str(i) for i in range(14)).issubset(keep))
        self.assertIn("449", candidates)
        self.assertLessEqual(len(keep), 34)

    def test_retention_no_delete_and_unverified_refused(self):
        with self.assertRaises(ValueError):
            guard.retention_candidates([{"utc": "2026-10-20T00:00:00+00:00", "backup": "x", "verified": False}])
        self.assertEqual(guard.retention_candidates([]), [])

    def test_cli_failure_hides_values(self):
        p = subprocess.run([sys.executable, "-B", str(SPEC.origin), "inspect", "--database", str(self.db),
                            "--revision", "secret-value", "--contract", str(self.root / "missing.json")],
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 1)
        self.assertNotIn("secret-value", p.stderr)
        self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main()
