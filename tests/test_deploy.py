"""Backup correctness and deployment contract checks; no Docker daemon required."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from deploy.backup import backup


class BackupTests(unittest.TestCase):
    def test_live_wal_backup_preserves_committed_records_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "live.sqlite3"
            target = Path(directory) / "backup.sqlite3"
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE artifacts(id INTEGER PRIMARY KEY, markdown TEXT)")
                connection.execute("INSERT INTO artifacts VALUES (1, '已保存的阶段成果')")
                connection.commit()
                backup(source, target)
                connection.execute("INSERT INTO artifacts VALUES (2, '备份后的新成果')")
                connection.commit()
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], 2)
            with closing(sqlite3.connect(target)) as restored:
                self.assertEqual(restored.execute("SELECT markdown FROM artifacts").fetchall(),
                                 [("已保存的阶段成果",)])
                self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_backup_never_overwrites_existing_backup_or_live_database(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "live.sqlite3"
            target = Path(directory) / "backup.sqlite3"
            with closing(sqlite3.connect(source)) as connection:
                connection.execute("CREATE TABLE marker(value TEXT)")
            target.write_bytes(b"previous backup")
            for destination in (source, target):
                with self.assertRaises(ValueError):
                    backup(source, destination)
            self.assertEqual(target.read_bytes(), b"previous backup")


if __name__ == "__main__":
    unittest.main()
