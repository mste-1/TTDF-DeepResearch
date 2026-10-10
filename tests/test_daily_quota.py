"""Daily admission limits against real SQLite; no model or search requests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from server.config import Settings
from server.db import Database
from server.errors import ServiceError


class DailyQuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        clock_patch = patch("server.db.now", return_value="2026-10-10T04:00:00.000Z")
        self.clock = clock_patch.start()
        self.addCleanup(clock_patch.stop)
        self.settings = Settings(data_dir=Path(self.temp.name), require_safe_sqlite=False)
        self.database = Database(self.settings)
        self.database.initialize()
        self.user = self.make_user("alice")

    def make_user(self, username, role="user"):
        return {"id": self.database.create_user(username, "test-password-123", role), "role": role}

    def submit(self, user=None, key=None, retry_of=None):
        return self.database.create_run(user or self.user, "研究城市交通", "", key or str(uuid.uuid4()), retry_of)

    def usage(self, day="2026-10-10"):
        with self.database.read() as con:
            row = con.execute("SELECT submissions FROM research_daily_usage WHERE day=?", (day,)).fetchone()
            return row[0] if row else 0

    def assert_quota_exhausted(self, user=None):
        with self.assertRaises(ServiceError) as raised:
            self.submit(user)
        self.assertEqual(raised.exception.code, "DAILY_RESEARCH_LIMIT")
        self.assertEqual(raised.exception.status, 429)
        self.assertFalse(raised.exception.retryable)
        self.assertTrue(any("\u4e00" <= ch <= "\u9fff" for ch in raised.exception.message))

    def test_defaults_and_all_users_share_five_submissions(self):
        self.assertEqual(self.settings.worker_count, 2)
        self.assertEqual(self.settings.daily_research_limit, 5)
        other = self.make_user("bob")
        admin = self.make_user("admin", "admin")
        for user in (self.user, other, self.user, other, admin):
            self.submit(user)
        for user in (self.user, other, admin):
            with self.subTest(role=user["role"], user=user["id"]):
                self.assert_quota_exhausted(user)
        self.assertEqual(self.usage(), 5)

    def test_idempotent_replay_succeeds_after_quota_exhaustion(self):
        first = self.submit(key="same-request")
        for _ in range(4):
            self.submit()
        self.assertEqual(self.submit(key="same-request")["id"], first["id"])
        self.assertEqual(self.usage(), 5)
        with self.assertRaises(ServiceError) as raised:
            self.database.create_run(self.user, "不同的主题", "", "same-request")
        self.assertEqual(raised.exception.code, "IDEMPOTENCY_CONFLICT")
        self.assert_quota_exhausted()

    def test_terminal_states_and_deletion_do_not_refund_submissions(self):
        cancelled = self.submit()
        self.database.cancel(cancelled["id"], self.user)
        self.database.delete(cancelled["id"], self.user)
        for status in ("failed", "interrupted", "completed", "completed_with_warnings"):
            run = self.submit()
            claimed = self.database.claim("test-manager")
            self.assertEqual(claimed["id"], run["id"])
            self.database.finish(run["id"], claimed["execution_id"], status,
                                 final="# 报告" if status.startswith("completed") else None)
            self.assertEqual(self.database.detail(run["id"], self.user)["status"], status)
            self.database.delete(run["id"], self.user)
        self.assertEqual(self.usage(), 5)
        # Initialization and a new Database instance must preserve consumed quota
        # even when all the original research records have been deleted.
        self.database = Database(self.settings)
        self.database.initialize()
        self.database.initialize()
        self.assertEqual(self.usage(), 5)
        self.assert_quota_exhausted()

    def test_regeneration_is_a_new_submission(self):
        original = self.submit()
        self.database.cancel(original["id"], self.user)
        regenerated = self.submit(key="regenerate-request", retry_of=original["id"])
        self.assertNotEqual(regenerated["id"], original["id"])
        self.assertEqual(regenerated["retry_of"], original["id"])
        self.assertEqual(self.usage(), 2)
        self.assertEqual(self.submit(key="regenerate-request", retry_of=original["id"])["id"],
                         regenerated["id"])
        for _ in range(3):
            self.submit()
        self.assert_quota_exhausted()

    def test_concurrent_admission_never_exceeds_five(self):
        def submit(index):
            try:
                return self.submit(key=f"concurrent-{index}")["id"]
            except ServiceError as exc:
                self.assertEqual(exc.code, "DAILY_RESEARCH_LIMIT")
                return None

        with ThreadPoolExecutor(max_workers=16) as executor:
            results = list(executor.map(submit, range(25)))
        self.assertEqual(len({value for value in results if value is not None}), 5)
        self.assertEqual(self.usage(), 5)
        with self.database.read() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0], 5)

    def test_quota_resets_at_beijing_midnight(self):
        self.clock.return_value = "2026-10-10T15:59:59.999Z"
        for _ in range(5):
            run = self.submit()
            self.database.cancel(run["id"], self.user)
        self.assert_quota_exhausted()
        self.clock.return_value = "2026-10-10T16:00:00.000Z"
        self.database.initialize()
        for _ in range(5):
            self.submit()
        self.assertEqual(self.usage("2026-10-10"), 5)
        self.assertEqual(self.usage("2026-10-11"), 5)
        self.database.initialize()
        self.assert_quota_exhausted()

    def test_v2_migration_backfills_beijing_days_and_preserves_runs(self):
        self.clock.return_value = "2026-10-09T15:59:59.999Z"
        previous_day = [self.submit() for _ in range(2)]
        self.clock.return_value = "2026-10-09T16:00:00.000Z"
        current_day = [self.submit() for _ in range(3)]
        # Build a schema-v2 fixture, whose quota table did not exist yet.
        with self.database.transaction() as con:
            con.execute("UPDATE research_runs SET status='failed' WHERE id=?", (current_day[0]["id"],))
            con.execute("UPDATE research_runs SET status='cancelled' WHERE id=?", (current_day[1]["id"],))
            con.execute("DROP TABLE research_daily_usage")
            con.execute("PRAGMA user_version=2")
        self.clock.return_value = "2026-10-10T04:00:00.000Z"
        self.database.initialize()
        self.assertEqual(self.usage("2026-10-09"), 2)
        self.assertEqual(self.usage("2026-10-10"), 3)
        for run in previous_day + current_day:
            self.assertEqual(self.database.detail(run["id"], self.user)["created_at"], run["created_at"])
        with self.database.read() as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0], 5)
        self.submit()
        self.submit()
        self.database.initialize()
        self.assertEqual(self.usage(), 5)
        self.assert_quota_exhausted()

    def test_full_queue_does_not_consume_daily_quota(self):
        self.database = Database(replace(self.settings, queue_capacity=1))
        first = self.submit()
        with self.assertRaises(ServiceError) as raised:
            self.submit(key="retry-after-full-queue")
        self.assertEqual(raised.exception.code, "QUEUE_FULL")
        self.assertEqual(self.usage(), 1)
        self.database.cancel(first["id"], self.user)
        self.submit(key="retry-after-full-queue")
        self.assertEqual(self.usage(), 2)

    def test_invalid_or_unauthorized_retry_does_not_consume_quota(self):
        other = self.make_user("bob")
        private_run = self.submit(other)
        for retry_of in (str(uuid.uuid4()), private_run["id"]):
            with self.subTest(retry_of=retry_of), self.assertRaises(ServiceError) as raised:
                self.submit(retry_of=retry_of)
            self.assertEqual(raised.exception.code, "NOT_FOUND")
        self.assertEqual(self.usage(), 1)
        for _ in range(4):
            self.submit()
        self.assert_quota_exhausted()

    def test_failed_creation_rolls_back_quota_and_run(self):
        with patch.object(self.database, "_event", side_effect=RuntimeError("write interrupted")):
            with self.assertRaisesRegex(RuntimeError, "write interrupted"):
                self.submit(key="atomic-submission")
        self.assertEqual(self.usage(), 0)
        with self.database.read() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0], 0)
        self.submit(key="atomic-submission")
        self.assertEqual(self.usage(), 1)


if __name__ == "__main__":
    unittest.main()
