"""Account command behavior and versioned database migration."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from server import admin_cli
from server.auth import verify_password
from server.config import Settings
from server.db import Database, SCHEMA_VERSION


class AdminAndMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.temp.name), require_safe_sqlite=False)
        self.database = Database(self.settings)
        self.database.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, password="initial-test-password"):
        output = StringIO()
        with patch.object(Settings, "from_env", return_value=self.settings), patch.object(admin_cli, "read_password", return_value=password), redirect_stdout(output):
            result = admin_cli.main(list(args))
        self.assertEqual(result, 0)
        self.assertNotIn(password, output.getvalue())
        return output.getvalue()

    def test_account_lifecycle_has_no_password_argument_or_output(self):
        self.cli("create", "reader", "--role", "admin")
        with self.database.read() as con:
            user = dict(con.execute("SELECT * FROM users WHERE username='reader'").fetchone())
        self.assertTrue(user["must_change_password"])
        self.assertEqual(user["role"], "admin")
        self.assertTrue(verify_password("initial-test-password", user["password_hash"]))
        self.assertIn("reader", self.cli("list"))
        self.cli("disable", "reader")
        with self.database.read() as con:
            self.assertEqual(con.execute("SELECT enabled FROM users WHERE id=?", (user["id"],)).fetchone()[0], 0)
        self.cli("enable", "reader")
        self.cli("reset", "reader", password="reset-test-password")
        with self.database.read() as con:
            changed = dict(con.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())
        self.assertEqual(changed["enabled"], 1)
        self.assertEqual(changed["must_change_password"], 1)
        self.assertTrue(verify_password("reset-test-password", changed["password_hash"]))

    def test_v1_migration_preserves_accounts_and_runs(self):
        user = {"id": self.database.create_user("reader", "initial-test-password"), "role": "user"}
        run = self.database.create_run(user, "保留研究", "", "migration-test-key")
        with self.database.transaction() as con:
            con.execute("ALTER TABLE research_artifacts DROP COLUMN source_url")
            con.execute("PRAGMA user_version=1")
        self.database.initialize()
        with self.database.read() as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
            self.assertIn("source_url", {row[1] for row in con.execute("PRAGMA table_info(research_artifacts)")})
        self.assertEqual(self.database.detail(run["id"], user)["topic"], "保留研究")


if __name__ == "__main__":
    unittest.main()
