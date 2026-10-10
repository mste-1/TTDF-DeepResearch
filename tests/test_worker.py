"""Actual spawned-process tests with explicit deterministic, unpaid test runners."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import gc
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import weakref

import psutil

from server.config import Settings
from server.db import Database, TERMINAL
from server.errors import ServiceError
from server.process_control import stop_process_tree
from server.worker import Execution, ManagerLock, WorkerManager


def test_runner(topic, instructions, emit, cancelled):
    emit({"type": "stage.started", "agent_instance_id": "draft", "payload": {"stage": "draft", "label": "草稿"}})
    draft = "已保存的草稿" + ("：" + instructions if instructions and topic != "orphan" else "")
    emit({"type": "artifact.created", "agent_instance_id": "draft", "payload": {"id": "saved-draft", "kind": "draft", "title": "初稿", "markdown": draft, "partial": False}})
    if topic == "orphan":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        emit({"type": "artifact.created", "payload": {"id": "descendant", "kind": "draft", "title": "进程清理验证", "markdown": str(child.pid)}})
        # Explicit test-only handshake: manager persists the PID before root exits.
        while not Path(instructions).is_file():
            time.sleep(0.01)
        os._exit(0)
    if topic == "crash":
        time.sleep(0.1)
        os._exit(7)
    if topic in {"hold", "ignore"}:
        while topic == "ignore" or not cancelled():
            time.sleep(0.02)
        return "取消时已返回的正文"
    if topic == "error":
        raise ValueError("this internal exception must not be exposed")
    if topic == "warning":
        emit({"type": "research.warning", "payload": {"code": "SEARCH_FALLBACK", "message": "检索摘要未完成"}})
    if topic == "thread_linger":
        threading.Thread(target=lambda: time.sleep(60), daemon=False).start()
    if topic == "executor_linger":
        executor = ThreadPoolExecutor(max_workers=1)
        executor.submit(time.sleep, 60)
    emit({"type": "stage.completed", "agent_instance_id": "draft", "payload": {"stage": "draft", "label": "草稿"}})
    return "# 完整报告\n\n测试结果"


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.temp.name), require_safe_sqlite=False,
                                 cancel_grace=0.1, process_exit_grace=0.15, poll_interval=0.02, execution_timeout=30)
        self.database = Database(self.settings)
        self.database.initialize()
        user_id = self.database.create_user("user", "initial-password", must_change_password=False)
        self.user = {"id": user_id, "role": "user"}
        self.manager = WorkerManager(self.settings, runner=test_runner, allow_test_runner=True)
        self.manager.start()
        self.serial = 0

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def submit(self, topic, instructions=""):
        self.serial += 1
        return self.database.create_run(self.user, topic, instructions, f"test-key-{self.serial}")

    def until(self, predicate, timeout=15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.manager.tick()
            if predicate():
                return
            time.sleep(0.02)
        self.fail("Worker invariant did not settle before the bounded test timeout")

    def detail(self, run):
        return self.database.detail(run["id"], self.user)

    def artifact_text(self, run, artifact_id="saved-draft", owner=None):
        with self.database.read() as con:
            self.database.authorize(con, run["id"], owner or self.user)
            return con.execute("SELECT markdown FROM research_artifacts WHERE run_id=? AND id=?", (run["id"], artifact_id)).fetchone()[0]

    def test_two_slots_fifo_single_user_and_cancel_does_not_stop_others(self):
        runs = [self.submit("hold") for _ in range(4)]
        self.until(lambda: len(self.manager.executions) == 2 and len(self.detail(runs[0])["artifacts"]) == 1)
        self.assertEqual(list(self.manager.executions), [r["id"] for r in runs[:2]])
        self.assertEqual(self.detail(runs[2])["queue_position"], 1)
        first = self.manager.executions[runs[0]["id"]]
        pid = first.process.pid
        self.database.cancel(runs[0]["id"], self.user)
        self.until(lambda: self.detail(runs[0])["status"] == "cancelled" and runs[2]["id"] in self.manager.executions)
        self.assertFalse(psutil.pid_exists(pid))
        self.assertEqual(len(self.manager.executions), 2)
        self.assertEqual(self.detail(runs[1])["status"], "running")
        self.assertEqual(self.artifact_text(runs[0]), "已保存的草稿")
        self.assertEqual(self.detail(runs[3])["status"], "queued")

    def test_startup_gate_lives_until_the_research_process_exits(self):
        event_refs = []
        make_event = self.manager.context.Event

        def track_event():
            event = make_event()
            event_refs.append(weakref.ref(event))
            return event

        run = self.submit("hold")
        with patch.object(self.manager.context, "Event", side_effect=track_event):
            self.manager.tick()
        gc.collect()
        # On POSIX, dropping the parent's final reference unlinks the named
        # semaphores while the spawned child may still be unpickling them.
        self.assertIsNotNone(event_refs[0](), "Startup gate was collected before the child finished")
        self.until(lambda: bool(self.detail(run)["artifacts"]))
        self.database.cancel(run["id"], self.user)
        self.until(lambda: self.detail(run)["status"] == "cancelled")
        gc.collect()
        self.assertIsNone(event_refs[0](), "Startup gate leaked after process cleanup")

    def test_timeout_kills_noncooperative_process_then_releases_slot(self):
        run = self.submit("ignore")
        self.until(lambda: bool(self.detail(run)["artifacts"]))
        execution = self.manager.executions[run["id"]]
        pid = execution.process.pid
        execution.started -= 31
        self.until(lambda: self.detail(run)["status"] in TERMINAL)
        detail = self.detail(run)
        self.assertEqual(detail["status"], "failed")
        self.assertEqual(detail["failure_code"], "TIMEOUT")
        self.assertFalse(psutil.pid_exists(pid))
        self.assertEqual(len(detail["artifacts"]), 1)
        with self.database.read() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM worker_slots WHERE state!='idle'").fetchone()[0], 0)

    def test_stop_before_session_creation_preserves_multiprocessing_exit_status(self):
        # A child stopped before _child_main calls setsid uses the tree fallback.
        process = self.manager.context.Process(target=time.sleep, args=(60,))
        process.start()
        try:
            created = psutil.Process(process.pid).create_time()
            stop_process_tree(process.pid, created)
            process.join(timeout=1)
            self.assertFalse(process.is_alive())
            self.assertIsNotNone(process.exitcode)
        finally:
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
            if not process.is_alive():
                process.close()

    def test_four_tasks_across_two_users_share_fifo_without_state_or_cancel_leakage(self):
        second_user = {"id": self.database.create_user("second-user", "initial-password", must_change_password=False), "role": "user"}
        owners = [self.user if index % 2 == 0 else second_user for index in range(4)]
        runs = [self.database.create_run(owner, "hold", f"task-{index}", f"mixed-task-{index}") for index, owner in enumerate(owners)]
        def detail(index):
            return self.database.detail(runs[index]["id"], owners[index])
        self.until(lambda: all(detail(index)["artifacts"] for index in range(2)))
        self.assertEqual(list(self.manager.executions), [run["id"] for run in runs[:2]])
        self.assertEqual(len({execution.process.pid for execution in self.manager.executions.values()}), 2)
        for index in range(2):
            self.assertEqual(self.artifact_text(runs[index], owner=owners[index]), f"已保存的草稿：task-{index}")
            other = second_user if owners[index]["id"] == self.user["id"] else self.user
            with self.assertRaises(ServiceError) as rejected:
                self.database.detail(runs[index]["id"], other)
            self.assertEqual(rejected.exception.code, "NOT_FOUND")
        self.assertEqual(detail(2)["queue_position"], 1)
        self.assertEqual(detail(3)["queue_position"], 2)
        stopped_pid = self.manager.executions[runs[0]["id"]].process.pid
        self.database.cancel(runs[0]["id"], self.user)
        self.until(lambda: detail(0)["status"] == "cancelled" and bool(detail(2)["artifacts"]))
        self.assertFalse(psutil.pid_exists(stopped_pid))
        self.assertEqual(len(self.manager.executions), 2)
        self.assertTrue(all(detail(index)["status"] == "running" for index in range(1, 3)))
        self.assertEqual(self.artifact_text(runs[2], owner=owners[2]), "已保存的草稿：task-2")
        self.assertEqual(detail(3)["status"], "queued")
        self.assertEqual(detail(3)["queue_position"], 1)

    def test_finished_warning_crash_error_and_isolated_results(self):
        runs = [self.submit(topic) for topic in ("success", "warning", "crash", "error")]
        self.until(lambda: all(self.detail(run)["status"] in TERMINAL for run in runs))
        self.assertEqual([self.detail(run)["status"] for run in runs], ["completed", "completed_with_warnings", "interrupted", "failed"])
        self.assertTrue(all(self.detail(run)["artifacts"] for run in runs))
        self.assertNotIn("internal exception", str([self.detail(r) for r in runs]))

    def test_manager_lock_and_recovery_preserve_artifacts_queued_jobs(self):
        second = WorkerManager(self.settings)
        with self.assertRaises(RuntimeError):
            second.start()
        # Simulate a dead generation whose child PID is still registered. Recovery must
        # kill the identity-matched process BEFORE making its slot available again.
        run = self.submit("ignore")
        self.until(lambda: bool(self.detail(run)["artifacts"]))
        execution = self.manager.executions[run["id"]]
        pid = execution.process.pid
        queued = self.submit("success")
        self.manager.lock.release()
        replacement = WorkerManager(self.settings, runner=test_runner, allow_test_runner=True)
        replacement.start()
        # The simulated old manager still owns this child. Reap the terminated
        # process before checking PID absence; a Linux zombie still has a PID.
        execution.process.join(timeout=1)
        self.assertFalse(psutil.pid_exists(pid))
        self.assertEqual(self.detail(run)["status"], "interrupted")
        self.assertTrue(self.detail(run)["artifacts"])
        self.assertEqual(self.detail(queued)["status"], "queued")
        execution.channel.close()
        if execution.job:
            execution.job.close()
        execution.process.close()
        self.manager.executions.clear()
        self.manager.started = False
        self.manager = replacement
        self.until(lambda: self.detail(queued)["status"] == "completed")

    def test_shrink_five_slots_recovers_high_slot_after_lock_and_preserves_reports(self):
        self.manager.close()
        legacy_settings = replace(self.settings, worker_count=5, daily_research_limit=10)
        self.database = Database(legacy_settings)
        self.manager = WorkerManager(legacy_settings, runner=test_runner, allow_test_runner=True)
        self.manager.start()
        report = self.submit("success")
        self.until(lambda: self.detail(report)["status"] == "completed")
        runs = [self.submit("ignore") for _ in range(5)]
        self.until(lambda: all(self.detail(run)["artifacts"] for run in runs))
        queued = self.submit("success")
        old_manager = self.manager
        executions = list(old_manager.executions.values())
        pids = [execution.process.pid for execution in executions]
        with self.database.read() as con:
            old_slots = [tuple(row) for row in con.execute("SELECT id,state,run_id,execution_id,pid FROM worker_slots ORDER BY id")]
        self.assertEqual(old_slots[4][2], runs[4]["id"])

        replacement = WorkerManager(self.settings, runner=test_runner, allow_test_runner=True)
        with self.assertRaisesRegex(RuntimeError, "already owns"):
            replacement.start()
        self.assertTrue(all(psutil.pid_exists(pid) for pid in pids))
        with self.database.read() as con:
            self.assertEqual([tuple(row) for row in con.execute("SELECT id,state,run_id,execution_id,pid FROM worker_slots ORDER BY id")], old_slots)

        # Simulate loss of the prior manager while all five registered children,
        # including the child in slot 4, still need recovery before shrinking.
        old_manager.lock.release()
        replacement.start()
        self.manager = replacement
        for execution in executions:
            execution.process.join(timeout=1)
            execution.channel.close()
            if execution.job:
                execution.job.close()
            execution.process.close()
        old_manager.executions.clear()
        old_manager.started = False
        self.assertTrue(all(not psutil.pid_exists(pid) for pid in pids))
        self.assertTrue(all(self.detail(run)["status"] == "interrupted" for run in runs))
        self.assertTrue(all(self.detail(run)["artifacts"] for run in runs))
        self.assertEqual(self.detail(report)["status"], "completed")
        self.assertEqual(self.artifact_text(report, "final-report"), "# 完整报告\n\n测试结果")
        self.assertEqual(self.detail(queued)["status"], "queued")
        with self.database.read() as con:
            self.assertEqual([tuple(row) for row in con.execute("SELECT id,state FROM worker_slots ORDER BY id")], [(0, "idle"), (1, "idle")])
        self.database = Database(self.settings)
        self.database.initialize()
        self.until(lambda: self.detail(queued)["status"] == "completed")

    def test_shrink_refuses_to_discard_unrecovered_slot(self):
        self.manager.close()
        with self.database.transaction() as con:
            con.execute("INSERT INTO worker_slots(id,state,run_id,execution_id) VALUES(4,'stopping','missing-run','missing-execution')")
        self.manager = WorkerManager(self.settings, runner=test_runner, allow_test_runner=True)
        with self.assertRaisesRegex(RuntimeError, "Cannot shrink"):
            self.manager.start()
        with self.database.read() as con:
            self.assertEqual(tuple(con.execute("SELECT state,run_id,execution_id FROM worker_slots WHERE id=4").fetchone()),
                             ("stopping", "missing-run", "missing-execution"))
        lock = ManagerLock(self.settings.data_dir / "manager.lock")
        lock.acquire()
        lock.release()

    def test_partial_ipc_frame_never_blocks_receiver(self):
        run = self.submit("success")
        claim = self.database.claim("manual")
        reader, writer = socket.socketpair()
        reader.setblocking(False)
        execution = Execution(claim, None, reader, None, 0)
        writer.sendall(b'{"kind":"event","event":')
        start = time.monotonic()
        self.manager.receive(execution)
        self.assertLess(time.monotonic() - start, 0.2)
        writer.close()
        self.manager.receive(execution)
        self.assertTrue(execution.eof)
        reader.close()
        self.database.finish(run["id"], claim["execution_id"], "interrupted")

    def test_fake_runner_cannot_be_enabled_implicitly(self):
        with self.assertRaises(ValueError):
            WorkerManager(self.settings, runner=test_runner)

    def test_one_spawn_failure_does_not_stop_other_executions(self):
        survivor = self.submit("hold")
        self.until(lambda: bool(self.detail(survivor)["artifacts"]))
        failed = self.submit("success")
        with patch("multiprocessing.process.BaseProcess.start", side_effect=OSError("process capacity")):
            self.manager.tick()
        self.assertEqual(self.detail(failed)["status"], "failed")
        self.assertEqual(self.detail(failed)["failure_code"], "PROCESS_START_FAILED")
        self.assertTrue(self.manager.executions[survivor["id"]].process.is_alive())
        self.assertEqual(self.detail(survivor)["status"], "running")

    def test_root_exit_reaps_remaining_descendants_before_slot_reuse(self):
        release = Path(self.temp.name) / "release-root"
        run = self.submit("orphan", str(release))
        descendant_pid = None
        try:
            self.until(lambda: any(a["id"] == "descendant" for a in self.detail(run)["artifacts"]))
            descendant_pid = int(self.artifact_text(run, "descendant"))
            self.assertTrue(psutil.pid_exists(descendant_pid))
            release.touch()
            self.until(lambda: self.detail(run)["status"] in TERMINAL)
            detail = self.detail(run)
            self.assertTrue(any(a["id"] == "descendant" for a in detail["artifacts"]), detail)
            descendant_pid = int(self.artifact_text(run, "descendant"))
            self.assertEqual(detail["status"], "interrupted")
            if psutil.pid_exists(descendant_pid):
                self.assertEqual(psutil.Process(descendant_pid).status(), psutil.STATUS_ZOMBIE)
            with self.database.read() as con:
                self.assertEqual(con.execute("SELECT COUNT(*) FROM worker_slots WHERE state!='idle'").fetchone()[0], 0)
        finally:
            if descendant_pid and psutil.pid_exists(descendant_pid):
                try:
                    psutil.Process(descendant_pid).kill()
                except psutil.NoSuchProcess:
                    pass

    def test_delivered_results_bound_thread_and_executor_shutdown_without_research_timeout(self):
        for topic in ("thread_linger", "executor_linger"):
            with self.subTest(topic=topic):
                run = self.submit(topic)
                self.until(lambda: self.manager.executions.get(run["id"]) is not None and
                           self.manager.executions[run["id"]].outcome_received_at is not None)
                execution = self.manager.executions[run["id"]]
                pid = execution.process.pid
                self.assertTrue(execution.process.is_alive())
                self.assertEqual(self.detail(run)["status"], "running")
                # Put delivery just before the research deadline. Subsequent
                # ticks cross it while only interpreter shutdown is pending.
                execution.started = execution.outcome_received_at - self.settings.execution_timeout + 0.01
                with self.database.read() as con:
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM worker_slots WHERE state='cleanup'").fetchone()[0], 1)
                self.until(lambda: self.detail(run)["status"] in TERMINAL)
                self.assertEqual(self.detail(run)["status"], "completed")
                self.assertIsNone(self.detail(run)["failure_code"])
                self.assertEqual(self.artifact_text(run, "final-report"), "# 完整报告\n\n测试结果")
                self.assertFalse(psutil.pid_exists(pid))
                with self.database.read() as con:
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM worker_slots WHERE state!='idle'").fetchone()[0], 0)

    def test_cancel_after_result_delivery_wins_over_bounded_shutdown_completion(self):
        run = self.submit("executor_linger")
        self.until(lambda: self.manager.executions.get(run["id"]) is not None and
                   self.manager.executions[run["id"]].outcome_received_at is not None)
        execution = self.manager.executions[run["id"]]
        pid = execution.process.pid
        self.assertTrue(execution.process.is_alive())
        cancelled = self.database.cancel(run["id"], self.user)
        self.assertEqual(cancelled["status"], "cancelling")
        self.until(lambda: self.detail(run)["status"] in TERMINAL)
        self.assertEqual(self.detail(run)["status"], "cancelled")
        self.assertEqual(self.artifact_text(run, "final-report"), "# 完整报告\n\n测试结果")
        self.assertFalse(psutil.pid_exists(pid))


if __name__ == "__main__":
    unittest.main()
