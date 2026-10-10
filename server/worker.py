"""One manager, two isolated research processes by default, durable FIFO scheduling.

Each process has its own socket and cancellation Event. Nonblocking incremental
framing ensures killing one writer halfway through a frame cannot block the pool.
The default runner is always the real Agent; tests must explicitly inject theirs.
"""
from dataclasses import dataclass, field
import json
import logging
import multiprocessing as mp
import os
from pathlib import Path
import signal
import socket
import sqlite3
import threading
import time

import psutil

from server.config import Settings
from server.db import Database, encode, now, uid
from server.process_control import WindowsJob, same_process, stop_process_tree

LOGGER = logging.getLogger("wenli.worker")
MAX_FRAME = 8 * 1024 * 1024


class ManagerLock:
    """OS releases this local-volume lock on process death; no stale lock guessing."""
    def __init__(self, path: Path):
        self.path, self.file = path, None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if os.fstat(self.file.fileno()).st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            self.file = None
            raise RuntimeError("A Worker manager already owns this data directory") from None

    def release(self):
        if self.file:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None


def _child_main(channel, gate, cancelled, parent_pid, parent_started, topic, instructions, runner):
    if os.name != "nt":
        os.setsid()

    def guard_parent():
        while True:
            time.sleep(0.3)
            if same_process(parent_pid, parent_started) is None:
                # Covers a crash between spawn and durable PID registration.
                if os.name != "nt":
                    os.killpg(os.getpid(), signal.SIGKILL)
                else:
                    for process in psutil.Process().children(recursive=True):
                        try:
                            process.kill()
                        except psutil.NoSuchProcess:
                            pass
                    os._exit(75)

    if same_process(parent_pid, parent_started) is None:
        return
    threading.Thread(target=guard_parent, daemon=True).start()
    while not gate.wait(0.2):
        if cancelled.is_set():
            return
    if cancelled.is_set():
        return
    channel.setblocking(True)
    send_lock = threading.Lock()

    def send(message):
        frame = (encode(message) + "\n").encode("utf-8")
        if len(frame) > MAX_FRAME:
            raise ValueError("Research event exceeds the bounded IPC frame size")
        with send_lock:
            channel.sendall(frame)

    try:
        if runner is None:
            from server.agent_adapter.runner import run_research
            runner = run_research
        result = runner(topic, instructions, lambda event: send({"kind": "event", "event": event}), cancelled.is_set)
        send({"kind": "result", "markdown": result})
    except BaseException as exc:
        try:
            send({"kind": "error", "code": "CANCELLED" if cancelled.is_set() else "RESEARCH_FAILED"})
        except (OSError, ValueError):
            pass
        LOGGER.error("Research process exited with %s", type(exc).__name__)
    finally:
        channel.close()


@dataclass
class Execution:
    run: dict
    process: object
    channel: socket.socket
    cancelled: object
    created: float
    started: float = field(default_factory=time.monotonic)
    buffer: bytearray = field(default_factory=bytearray)
    result: str | None = None
    failure_code: str | None = None
    stop_reason: str | None = None
    stopping_at: float | None = None
    exited_at: float | None = None
    eof: bool = False
    job: object = None
    outcome_received_at: float | None = None
    exit_cleanup_forced: bool = False
    # POSIX spawn rebuilds named semaphores asynchronously. Keep the parent's
    # Event alive until child cleanup so its finalizer cannot unlink them early.
    startup_gate: object = None


class WorkerManager:
    def __init__(self, settings=None, *, runner=None, allow_test_runner=False):
        if runner is not None and not allow_test_runner:
            raise ValueError("An injected runner is allowed only in explicit tests")
        self.settings = settings or Settings.from_env()
        self.database = Database(self.settings)
        self.manager_id = uid()
        self.lock = ManagerLock(self.settings.data_dir / "manager.lock")
        self.context = mp.get_context("spawn")
        self.executions: dict[str, Execution] = {}
        self.runner = runner
        self.started = False
        self.stopping = False
        self.last_heartbeat = 0.0
        self.last_cleanup = 0.0

    def start(self):
        self.database.initialize()
        self.lock.acquire()
        try:
            self.recover()
            # Recovery needs every persisted slot, including slots removed by a
            # capacity reduction. Only the manager holding the lock may prune them.
            with self.database.transaction() as con:
                occupied = con.execute("""SELECT 1 FROM worker_slots WHERE id>=?
                    AND (state!='idle' OR run_id IS NOT NULL OR execution_id IS NOT NULL OR pid IS NOT NULL)
                    LIMIT 1""", (self.settings.worker_count,)).fetchone()
                if occupied:
                    raise RuntimeError("Cannot shrink worker slots before prior executions are cleaned up")
                con.execute("DELETE FROM worker_slots WHERE id>=? AND state='idle'", (self.settings.worker_count,))
            self.heartbeat()
            self.database.cleanup_events()
            self.started = True
        except BaseException:
            self.lock.release()
            raise

    def recover(self):
        with self.database.read() as con:
            slots = [dict(r) for r in con.execute("SELECT * FROM worker_slots WHERE state!='idle'")]
        for slot in slots:
            job = WindowsJob.open(slot["execution_id"]) if slot["execution_id"] else None
            try:
                if job:
                    job.stop()
                elif slot["pid"]:
                    stop_process_tree(slot["pid"], slot["process_started"])
            finally:
                if job:
                    job.close()
            self.database.finish(slot["run_id"], slot["execution_id"], "interrupted", failure_code="WORKER_RESTARTED")
        # A stopped/dead execution may have been terminalized just before manager death.
        with self.database.transaction() as con:
            orphaned = con.execute("SELECT id FROM research_runs WHERE status IN ('running','cancelling') AND id NOT IN (SELECT run_id FROM worker_slots WHERE run_id IS NOT NULL)").fetchall()
            for run in orphaned:
                self.database._finish(con, run["id"], "interrupted", "WORKER_RESTARTED")

    def heartbeat(self, healthy=True):
        with self.database.transaction() as con:
            con.execute("INSERT INTO manager_state(id,manager_id,heartbeat_at,healthy) VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET manager_id=excluded.manager_id,heartbeat_at=excluded.heartbeat_at,healthy=excluded.healthy",
                        (self.manager_id, now(), int(healthy)))
        self.last_heartbeat = time.monotonic()

    def launch(self, run):
        parent, child = socket.socketpair()
        parent.setblocking(False)
        gate, cancelled = self.context.Event(), self.context.Event()
        process = self.context.Process(target=_child_main, args=(child, gate, cancelled,
            os.getpid(), psutil.Process().create_time(), run["topic"], run["instructions"], self.runner),
            name=f"wenli-{run['id'][:8]}")
        claimed_at = run.get("claimed_monotonic", time.monotonic())
        job = None
        try:
            job = WindowsJob.create(run["execution_id"])
            process.start()
            created = psutil.Process(process.pid).create_time()
            execution = Execution(run, process, parent, cancelled, created,
                                  started=claimed_at, job=job, startup_gate=gate)
            # Keep a local handle before any DB operation, including a failed registration.
            self.executions[run["id"]] = execution
            if job:
                job.assign(process.pid)
            self.database.register_process(run["slot_id"], run["execution_id"], process.pid, created)
            gate.set()
        except BaseException as exc:
            if job:
                job.stop()
                job.close()
            if process.pid:
                created = psutil.Process(process.pid).create_time() if process.is_alive() else None
                if created is not None:
                    stop_process_tree(process.pid, created)
                process.join(timeout=1)
            parent.close()
            self.executions.pop(run["id"], None)
            self.database.finish(run["id"], run["execution_id"], "failed", failure_code="PROCESS_START_FAILED")
            if isinstance(exc, (sqlite3.Error, KeyboardInterrupt, SystemExit)):
                raise
            LOGGER.error("One research process could not start (%s)", type(exc).__name__)
        finally:
            child.close()

    def request_stop(self, execution, reason):
        if execution.stopping_at is None:
            execution.stop_reason, execution.stopping_at = reason, time.monotonic()
            execution.cancelled.set()
            with self.database.transaction() as con:
                con.execute("UPDATE worker_slots SET state='stopping' WHERE execution_id=?", (execution.run["execution_id"],))

    @staticmethod
    def stop_execution(execution):
        if execution.job:
            execution.job.stop()
        else:
            stop_process_tree(execution.process.pid, execution.created)

    def receive(self, execution):
        # Bounded and fair: at most 64 messages and 256 KiB per task per tick.
        received, processed = 0, 0
        while processed < 64:
            newline = execution.buffer.find(b"\n")
            if newline >= 0:
                raw = bytes(execution.buffer[:newline])
                # Remove only after a successful database commit; retry on storage failure.
                try:
                    message = json.loads(raw)
                except (ValueError, UnicodeError):
                    execution.failure_code = "IPC_INVALID"
                    self.request_stop(execution, "failed")
                    del execution.buffer[:newline + 1]
                    continue
                kind = message.get("kind")
                if kind == "event":
                    self.database.ingest(execution.run["id"], execution.run["execution_id"], message.get("event"))
                elif kind == "result":
                    value = message.get("markdown")
                    if isinstance(value, str):
                        execution.result = value
                    else:
                        execution.failure_code = "EMPTY_REPORT"
                elif kind == "error":
                    execution.failure_code = message.get("code", "RESEARCH_FAILED")
                if kind in {"result", "error"} and execution.outcome_received_at is None:
                    execution.outcome_received_at = time.monotonic()
                    with self.database.transaction() as con:
                        con.execute("UPDATE worker_slots SET state='cleanup' WHERE execution_id=? AND state IN ('starting','running')",
                                    (execution.run["execution_id"],))
                del execution.buffer[:newline + 1]
                processed += 1
                continue
            if execution.eof or received >= 256 * 1024:
                return
            try:
                chunk = execution.channel.recv(65536)
            except BlockingIOError:
                return
            except (ConnectionResetError, OSError):
                execution.eof = True
                return
            if not chunk:
                execution.eof = True
                return
            received += len(chunk)
            execution.buffer.extend(chunk)
            if len(execution.buffer) > MAX_FRAME:
                execution.failure_code = "IPC_TOO_LARGE"
                execution.buffer.clear()
                self.request_stop(execution, "failed")
                return

    def tick(self, *, allow_claim=True):
        if not self.started:
            raise RuntimeError("Start the manager before polling")
        clock = time.monotonic()
        for run_id, execution in list(self.executions.items()):
            self.receive(execution)
            with self.database.read() as con:
                row = con.execute("SELECT status FROM research_runs WHERE id=?", (run_id,)).fetchone()
            if row and row[0] == "cancelling":
                self.request_stop(execution, "cancelled")
            elif (execution.outcome_received_at or clock) - execution.started >= self.settings.execution_timeout:
                self.request_stop(execution, "timeout")
            if self.stopping:
                self.request_stop(execution, "interrupted")
            if execution.stopping_at is not None and clock - execution.stopping_at >= self.settings.cancel_grace:
                self.stop_execution(execution)
            if (execution.outcome_received_at is not None and execution.process.is_alive()
                    and clock - execution.outcome_received_at >= self.settings.process_exit_grace):
                # The research result has arrived; only interpreter/SDK shutdown
                # remains. Non-daemon tracer or executor threads must not hold a
                # slot until the research timeout, or turn a valid result into it.
                self.stop_execution(execution)
                execution.exit_cleanup_forced = True
            if not execution.process.is_alive():
                execution.process.join(timeout=0)
                execution.exited_at = execution.exited_at or clock
                # Root exit alone does not prove its subprocesses have exited.
                self.stop_execution(execution)
                # Drain complete frames after exit; never wait on an incomplete frame.
                self.receive(execution)
                if not execution.eof and clock - execution.exited_at < 2:
                    continue
                if b"\n" in execution.buffer:
                    continue
                status, code = "completed", execution.failure_code
                if execution.stop_reason == "timeout":
                    status, code = "failed", "TIMEOUT"
                elif execution.stop_reason == "cancelled":
                    status, code = "cancelled", None
                elif execution.stop_reason == "interrupted":
                    status, code = "interrupted", "WORKER_STOPPED"
                elif execution.failure_code:
                    status = "failed"
                elif execution.result is None or (execution.process.exitcode != 0 and not execution.exit_cleanup_forced):
                    status, code = "interrupted", "PROCESS_EXITED"
                self.database.finish(run_id, execution.run["execution_id"], status, execution.result, code)
                execution.channel.close()
                if execution.job:
                    execution.job.close()
                execution.process.close()
                del self.executions[run_id]
        if not self.stopping and allow_claim:
            while len(self.executions) < self.settings.worker_count:
                run = self.database.claim(self.manager_id)
                if run is None:
                    break
                run["claimed_monotonic"] = time.monotonic()
                self.launch(run)
        if clock - self.last_heartbeat >= 5:
            self.heartbeat()
        if clock - self.last_cleanup >= 60:
            self.database.cleanup_events()
            self.last_cleanup = clock

    def close(self):
        if not self.started:
            return
        self.stopping = True
        try:
            while self.executions:
                self.tick(allow_claim=False)
                time.sleep(self.settings.poll_interval)
            self.heartbeat(healthy=False)
        finally:
            # If cleanup/storage failed, do not allow old research to survive lock release.
            for execution in self.executions.values():
                self.stop_execution(execution)
                if execution.job:
                    execution.job.close()
                execution.channel.close()
            self.lock.release()
            self.started = False

    def run_forever(self):
        self.start()
        try:
            while not self.stopping:
                try:
                    self.tick()
                except sqlite3.Error:
                    # Stop new claims, bound memory, and stop executing work on persistence loss.
                    LOGGER.error("Research storage unavailable; stopping executions")
                    for execution in self.executions.values():
                        execution.cancelled.set()
                        self.stop_execution(execution)
                    raise
                time.sleep(self.settings.poll_interval)
        finally:
            self.close()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    manager = WorkerManager()
    def stopping(_signal, _frame):
        manager.stopping = True
    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    manager.run_forever()


if __name__ == "__main__":
    main()
