"""SQLite persistence. Every externally visible transition is one short transaction."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import sqlite3
import uuid

from server.auth import hash_password
from server.config import Settings
from server.errors import ServiceError

TERMINAL = {"completed", "completed_with_warnings", "cancelled", "failed", "interrupted"}
ACTIVE = {"running", "cancelling"}
SCHEMA_VERSION = 3
BEIJING_TIME = timezone(timedelta(hours=8))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def later(value: str, **kwargs) -> str:
    return (datetime.fromisoformat(value.replace("Z", "+00:00")) + timedelta(**kwargs)).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def uid() -> str:
    return str(uuid.uuid4())


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('user','admin')), enabled INTEGER NOT NULL DEFAULT 1,
 must_change_password INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, password_changed_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 csrf_token TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_runs (
 queue_seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 user_id TEXT NOT NULL REFERENCES users(id), topic TEXT NOT NULL, instructions TEXT NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
 has_warnings INTEGER NOT NULL DEFAULT 0, last_event_seq INTEGER NOT NULL DEFAULT 0,
 history_available INTEGER NOT NULL DEFAULT 1, events_expire_at TEXT,
 snapshot_json TEXT NOT NULL DEFAULT '{"nodes":[],"edges":[]}',
 idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, retry_of TEXT,
 execution_id TEXT, manager_id TEXT, failure_code TEXT,
 UNIQUE(user_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS runs_queue ON research_runs(status,queue_seq);
CREATE INDEX IF NOT EXISTS runs_owner ON research_runs(user_id,queue_seq);
CREATE TABLE IF NOT EXISTS research_daily_usage (
 day TEXT PRIMARY KEY, submissions INTEGER NOT NULL CHECK(submissions >= 0)
);
CREATE TABLE IF NOT EXISTS worker_slots (
 id INTEGER PRIMARY KEY, state TEXT NOT NULL DEFAULT 'idle', run_id TEXT UNIQUE,
 execution_id TEXT, manager_id TEXT, pid INTEGER, process_started REAL
);
CREATE TABLE IF NOT EXISTS manager_state (id INTEGER PRIMARY KEY CHECK(id=1), manager_id TEXT NOT NULL,
 heartbeat_at TEXT NOT NULL, healthy INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS research_events (
 run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE, seq INTEGER NOT NULL,
 data TEXT NOT NULL, PRIMARY KEY(run_id,seq)
);
CREATE TABLE IF NOT EXISTS research_artifacts (
 id TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
 kind TEXT NOT NULL, title TEXT NOT NULL, markdown TEXT NOT NULL, partial INTEGER NOT NULL,
 version INTEGER NOT NULL, agent_instance_id TEXT, source_url TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(run_id,id)
);
CREATE TABLE IF NOT EXISTS research_sources (
 run_id TEXT NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE, url TEXT NOT NULL,
 title TEXT NOT NULL, query TEXT NOT NULL, agent_instance_id TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(run_id,url,agent_instance_id,query)
);
"""


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings

    def connect(self):
        con = sqlite3.connect(str(self.settings.database), timeout=5, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=5000")
        return con

    def initialize(self):
        version = sqlite3.sqlite_version_info
        safe = version >= (3, 51, 3) or ((3, 50, 7) <= version < (3, 51, 0)) or ((3, 44, 6) <= version < (3, 45, 0))
        if self.settings.require_safe_sqlite and not safe:
            raise RuntimeError("SQLite runtime lacks the required WAL-reset fix; use the supplied deployment image")
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("BEGIN IMMEDIATE")
            try:
                version = con.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2, SCHEMA_VERSION):
                    raise RuntimeError("Unsupported database migration version")
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        con.execute(statement)
                if version == 1 and "source_url" not in {r[1] for r in con.execute("PRAGMA table_info(research_artifacts)")}:
                    con.execute("ALTER TABLE research_artifacts ADD COLUMN source_url TEXT")
                if version < 3:
                    con.execute("""INSERT INTO research_daily_usage(day,submissions)
                        SELECT date(r.created_at, '+8 hours'), COUNT(*) FROM research_runs r
                        JOIN users u ON u.id=r.user_id WHERE u.role!='admin'
                        GROUP BY date(r.created_at, '+8 hours')
                        ON CONFLICT(day) DO UPDATE SET submissions=MAX(submissions,excluded.submissions)""")
                con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                con.executemany("INSERT OR IGNORE INTO worker_slots(id) VALUES(?)",
                                [(i,) for i in range(self.settings.worker_count)])
                # The manager must recover old executions under its lock before
                # removing slots that exceed a reduced concurrency setting.
                con.commit()
            except BaseException:
                con.rollback()
                raise

    @contextmanager
    def transaction(self):
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    @contextmanager
    def read(self):
        con = self.connect()
        try:
            con.execute("BEGIN")
            yield con
        finally:
            con.rollback()
            con.close()

    def create_user(self, username, password, role="user", must_change_password=True):
        if not username or len(username) > 64 or any(ch.isspace() for ch in username):
            raise ServiceError("USERNAME_INVALID", "账号须为不含空白的 1 至 64 个字符。")
        encoded = hash_password(password)
        user_id = uid()
        try:
            with self.transaction() as con:
                con.execute("INSERT INTO users(id,username,password_hash,role,must_change_password,created_at) VALUES(?,?,?,?,?,?)",
                            (user_id, username, encoded, role, int(must_change_password), now()))
        except sqlite3.IntegrityError as exc:
            raise ServiceError("ACCOUNT_EXISTS", "账号已存在。", 409) from exc
        return user_id

    def authorize(self, con, run_id, user, write=False):
        run = con.execute("SELECT * FROM research_runs WHERE id=?", (run_id,)).fetchone()
        if run is None or (run["user_id"] != user["id"] and (write or user["role"] != "admin")):
            raise ServiceError("NOT_FOUND", "研究任务不存在或无权访问。", 404)
        return run

    def public_run(self, con, row, detailed=True):
        fields = ("id", "user_id", "topic", "instructions", "status", "created_at", "started_at", "finished_at",
                  "last_event_seq", "retry_of", "failure_code")
        result = {key: row[key] for key in fields}
        result["username"] = con.execute("SELECT username FROM users WHERE id=?", (row["user_id"],)).fetchone()[0]
        result["has_warnings"] = bool(row["has_warnings"])
        snapshot = json.loads(row["snapshot_json"])
        result["warnings"] = snapshot.get("warnings", [])
        result["history_available"] = bool(row["history_available"])
        result["queue_position"] = (con.execute(
            "SELECT COUNT(*) FROM research_runs WHERE status='queued' AND queue_seq<=?", (row["queue_seq"],)
        ).fetchone()[0] if row["status"] == "queued" else None)
        if detailed:
            result["snapshot"] = snapshot
            result["artifacts"] = [self.public_artifact(x, include_markdown=False) for x in con.execute(
                "SELECT id,kind,title,partial,version,agent_instance_id,source_url,created_at,updated_at FROM research_artifacts WHERE run_id=? ORDER BY created_at,id", (row["id"],))]
            result["sources"] = [dict(x) for x in con.execute(
                "SELECT url,title,query,agent_instance_id FROM research_sources WHERE run_id=? ORDER BY rowid", (row["id"],))]
        return result

    @staticmethod
    def public_artifact(row, include_markdown=True):
        fields = ("id", "kind", "title", "version", "agent_instance_id", "source_url", "created_at", "updated_at")
        if include_markdown:
            fields += ("markdown",)
        return {**{key: row[key] for key in fields}, "partial": bool(row["partial"])}

    def detail(self, run_id, user):
        with self.read() as con:
            return self.public_run(con, self.authorize(con, run_id, user))

    def create_run(self, user, topic, instructions, key, retry_of=None):
        digest = hashlib.sha256(encode([topic, instructions, retry_of]).encode()).hexdigest()
        with self.transaction() as con:
            prior = con.execute("SELECT * FROM research_runs WHERE user_id=? AND idempotency_key=?", (user["id"], key)).fetchone()
            if prior:
                if prior["request_hash"] != digest:
                    raise ServiceError("IDEMPOTENCY_CONFLICT", "该提交标识已用于不同的研究需求。", 409)
                return self.public_run(con, prior)
            if retry_of:
                self.authorize(con, retry_of, user)
            timestamp = now()
            day = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(BEIJING_TIME).date().isoformat()
            # The role comes from the authenticated server session, not request data.
            counts_toward_quota = user["role"] != "admin"
            if counts_toward_quota:
                usage = con.execute("SELECT submissions FROM research_daily_usage WHERE day=?", (day,)).fetchone()
                if usage and usage["submissions"] >= self.settings.daily_research_limit:
                    raise ServiceError("DAILY_RESEARCH_LIMIT",
                                       f"普通账户今日共享研究提交已达 {self.settings.daily_research_limit} 次上限，请于北京时间次日 00:00 后再试。",
                                       429)
            queued = con.execute("SELECT COUNT(*) FROM research_runs WHERE status='queued'").fetchone()[0]
            if queued >= self.settings.queue_capacity:
                raise ServiceError("QUEUE_FULL", "等待队列已满，请稍后重试。", 429, True)
            run_id = uid()
            if counts_toward_quota:
                con.execute("""INSERT INTO research_daily_usage(day,submissions) VALUES(?,1)
                    ON CONFLICT(day) DO UPDATE SET submissions=submissions+1""", (day,))
            con.execute("INSERT INTO research_runs(id,user_id,topic,instructions,status,created_at,idempotency_key,request_hash,retry_of) VALUES(?,?,?,?,'queued',?,?,?,?)",
                        (run_id, user["id"], topic, instructions, timestamp, key, digest, retry_of))
            self._event(con, run_id, {"type": "run.queued", "payload": {}})
            return self.public_run(con, con.execute("SELECT * FROM research_runs WHERE id=?", (run_id,)).fetchone())

    def cancel(self, run_id, user):
        with self.transaction() as con:
            run = self.authorize(con, run_id, user, write=True)
            if run["status"] == "queued":
                self._finish(con, run_id, "cancelled")
            elif run["status"] == "running":
                con.execute("UPDATE research_runs SET status='cancelling' WHERE id=?", (run_id,))
                self._event(con, run_id, {"type": "run.cancelling", "payload": {}})
            return self.public_run(con, con.execute("SELECT * FROM research_runs WHERE id=?", (run_id,)).fetchone())

    def delete(self, run_id, user):
        with self.transaction() as con:
            run = self.authorize(con, run_id, user, write=True)
            occupied = con.execute("SELECT 1 FROM worker_slots WHERE run_id=?", (run_id,)).fetchone()
            if run["status"] not in TERMINAL or occupied:
                raise ServiceError("TASK_ACTIVE", "请先终止研究并等待进程清理完成。", 409)
            con.execute("DELETE FROM research_runs WHERE id=?", (run_id,))

    def claim(self, manager_id):
        with self.transaction() as con:
            slot = con.execute("SELECT * FROM worker_slots WHERE state='idle' AND id<? ORDER BY id LIMIT 1",
                               (self.settings.worker_count,)).fetchone()
            run = con.execute("SELECT * FROM research_runs WHERE status='queued' ORDER BY queue_seq LIMIT 1").fetchone()
            if not slot or not run:
                return None
            execution = uid()
            con.execute("UPDATE worker_slots SET state='starting',run_id=?,execution_id=?,manager_id=? WHERE id=?",
                        (run["id"], execution, manager_id, slot["id"]))
            con.execute("UPDATE research_runs SET status='running',started_at=?,execution_id=?,manager_id=? WHERE id=?",
                        (now(), execution, manager_id, run["id"]))
            self._event(con, run["id"], {"type": "run.started", "payload": {}})
            return {**dict(run), "execution_id": execution, "slot_id": slot["id"]}

    def register_process(self, slot, execution, pid, process_started):
        with self.transaction() as con:
            con.execute("UPDATE worker_slots SET state='running',pid=?,process_started=? WHERE id=? AND execution_id=?",
                        (pid, process_started, slot, execution))

    def ingest(self, run_id, execution, event):
        event = normalize_event(event)
        if event is None:
            return
        with self.transaction() as con:
            run = con.execute("SELECT status,execution_id FROM research_runs WHERE id=?", (run_id,)).fetchone()
            if not run or run["execution_id"] != execution or run["status"] not in ACTIVE:
                return
            self._event(con, run_id, event)

    def _event(self, con, run_id, event):
        row = con.execute("SELECT last_event_seq,snapshot_json FROM research_runs WHERE id=?", (run_id,)).fetchone()
        seq, timestamp = row["last_event_seq"] + 1, now()
        snapshot = json.loads(row["snapshot_json"])
        payload = dict(event.get("payload", {}))
        event_type = event["type"]
        agent = event.get("agent_instance_id")
        if event_type == "artifact.created":
            artifact_id = payload.get("id") or uid()
            kind = payload.get("kind", "draft")
            prior = con.execute("SELECT * FROM research_artifacts WHERE run_id=? AND id=?", (run_id, artifact_id)).fetchone()
            if prior and not prior["partial"] and payload.get("partial", False):
                # A late token frame cannot downgrade an already complete artifact.
                payload.update(markdown=prior["markdown"], partial=False, title=prior["title"])
            if prior:
                kind = prior["kind"]
            version = prior["version"] if prior else con.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM research_artifacts WHERE run_id=? AND kind=?", (run_id, kind)).fetchone()[0]
            con.execute("""INSERT INTO research_artifacts(id,run_id,kind,title,markdown,partial,version,agent_instance_id,source_url,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id,id) DO UPDATE SET markdown=excluded.markdown,
                partial=excluded.partial,title=excluded.title,source_url=COALESCE(excluded.source_url,research_artifacts.source_url),updated_at=excluded.updated_at""",
                (artifact_id, run_id, kind, payload.get("title", "阶段成果"), payload.get("markdown", ""),
                 int(payload.get("partial", False)), version, payload.get("agent_instance_id") or agent,
                 payload.get("source_url"), timestamp, timestamp))
            payload = {"artifact_id": artifact_id, "kind": kind, "title": payload.get("title", "阶段成果"),
                       "partial": bool(payload.get("partial", False)), "version": version}
        elif event_type == "source.discovered":
            con.execute("INSERT OR REPLACE INTO research_sources(run_id,url,title,query,agent_instance_id) VALUES(?,?,?,?,?)",
                        (run_id, payload["url"], payload.get("title", ""), payload.get("query", ""), agent or ""))
        elif event_type == "research.warning":
            con.execute("UPDATE research_runs SET has_warnings=1 WHERE id=?", (run_id,))
            warning = {"code": payload.get("code", "RESEARCH_WARNING"), "message": payload.get("message", "研究步骤存在异常。")}
            warnings = snapshot.setdefault("warnings", [])
            if warning not in warnings:
                warnings.append(warning)
        elif event_type == "quality.evaluated":
            artifact_id = f"evaluation-{agent or uid()}"
            scores = payload.get("scores", {})
            markdown = "# 模型评估\n\n" + "\n".join(f"- {key}: {value}" for key, value in scores.items())
            if payload.get("feedback"):
                markdown += "\n\n" + payload["feedback"]
            con.execute("""INSERT INTO research_artifacts(id,run_id,kind,title,markdown,partial,version,agent_instance_id,created_at,updated_at)
                VALUES(?,?,'evaluation','模型评估',?,0,1,?,?,?) ON CONFLICT(run_id,id) DO UPDATE SET
                markdown=excluded.markdown,updated_at=excluded.updated_at""", (artifact_id, run_id, markdown, agent, timestamp, timestamp))
            payload["artifact_id"] = artifact_id
        if agent and event_type in {"stage.started", "stage.completed", "research.dispatched", "research.started", "research.completed"}:
            node = next((n for n in snapshot["nodes"] if n["id"] == agent), None)
            if node is None:
                node = {"id": agent, "label": payload.get("label", payload.get("topic", "研究阶段")),
                        "stage": payload.get("stage", "research"), "status": "pending"}
                snapshot["nodes"].append(node)
            node["status"] = payload.get("status", "completed") if event_type.endswith("completed") else ("pending" if event_type.endswith("dispatched") else "running")
            if payload.get("label"):
                node["label"] = payload["label"]
            if payload.get("stage"):
                node["stage"] = payload["stage"]
            if event.get("iteration") is not None:
                node["iteration"] = event["iteration"]
            parent = event.get("parent_instance_id")
            if parent and parent != agent:
                node["parent_id"] = parent
                edge_id = f"{parent}:{agent}"
                if any(n["id"] == parent for n in snapshot["nodes"]) and not any(e["id"] == edge_id for e in snapshot["edges"]):
                    label = {"research": "分发主题", "red_team": "发起审阅", "evaluation": "评价草稿",
                             "refine": "修订草稿", "final": "汇总成稿"}.get(node["stage"], "传递成果")
                    snapshot["edges"].append({"id": edge_id, "source": parent, "target": agent, "label": label})
                has_research_result = (event_type == "research.completed" and node["status"] == "completed"
                    and con.execute("SELECT 1 FROM research_artifacts WHERE run_id=? AND agent_instance_id=? AND kind='research' AND partial=0 AND TRIM(markdown)<>'' LIMIT 1",
                                    (run_id, agent)).fetchone() is not None)
                if has_research_result and any(n["id"] == parent for n in snapshot["nodes"]):
                    returned = f"{agent}:{parent}:result"
                    if not any(e["id"] == returned for e in snapshot["edges"]):
                        snapshot["edges"].append({"id": returned, "source": agent, "target": parent, "label": "返回成果"})
        if event_type == "artifact.created" and payload.get("kind") == "critique" and agent:
            critic = next((n for n in snapshot["nodes"] if n["id"] == agent), None)
            parent = critic.get("parent_id") if critic else None
            if parent and any(n["id"] == parent for n in snapshot["nodes"]):
                feedback_id = f"{agent}:{parent}:critique"
                if not any(e["id"] == feedback_id for e in snapshot["edges"]):
                    snapshot["edges"].append({"id": feedback_id, "source": agent, "target": parent, "label": "返回质疑"})
        if event_type.startswith("run.") and event_type.split(".", 1)[1] in TERMINAL:
            for node in snapshot["nodes"]:
                if node["status"] in {"running", "pending"}:
                    node["status"] = "interrupted"
        public = {"schema_version": 1, "run_id": run_id, "seq": seq, "event_id": uid(), "type": event_type,
                  "timestamp": timestamp, "payload": payload}
        for key in ("agent_instance_id", "parent_instance_id", "iteration", "tool_call_id"):
            if event.get(key) is not None:
                public[key] = event[key]
        con.execute("INSERT INTO research_events(run_id,seq,data) VALUES(?,?,?)", (run_id, seq, encode(public)))
        con.execute("UPDATE research_runs SET last_event_seq=?,snapshot_json=? WHERE id=?", (seq, encode(snapshot), run_id))

    def finish(self, run_id, execution, status, final=None, failure_code=None):
        """Caller MUST confirm the child has exited before terminalizing/releasing."""
        with self.transaction() as con:
            run = con.execute("SELECT * FROM research_runs WHERE id=?", (run_id,)).fetchone()
            if not run or run["execution_id"] != execution:
                return
            if run["status"] in ACTIVE:
                if final and final.strip():
                    existing_final = con.execute("SELECT id FROM research_artifacts WHERE run_id=? AND kind='final' ORDER BY updated_at DESC LIMIT 1", (run_id,)).fetchone()
                    self._event(con, run_id, {"type": "artifact.created", "payload": {
                        "id": existing_final[0] if existing_final else "final-report", "kind": "final", "title": "最终报告", "markdown": final, "partial": False}})
                if run["status"] == "cancelling" and failure_code != "WORKER_RESTARTED":
                    status, failure_code = "cancelled", None
                elif status == "completed":
                    if not final or not final.strip():
                        status, failure_code = "failed", "EMPTY_REPORT"
                    elif run["has_warnings"]:
                        status = "completed_with_warnings"
                self._finish(con, run_id, status, failure_code)
            con.execute("UPDATE worker_slots SET state='idle',run_id=NULL,execution_id=NULL,manager_id=NULL,pid=NULL,process_started=NULL WHERE execution_id=?", (execution,))

    def _finish(self, con, run_id, status, failure_code=None):
        finished = now()
        con.execute("UPDATE research_runs SET status=?,finished_at=?,events_expire_at=?,failure_code=? WHERE id=?",
                    (status, finished, later(finished, days=self.settings.event_retention_days), failure_code, run_id))
        warnings = bool(con.execute("SELECT has_warnings FROM research_runs WHERE id=?", (run_id,)).fetchone()[0])
        self._event(con, run_id, {"type": "run.completed" if status == "completed_with_warnings" else f"run.{status}",
                                "payload": {"status": status, "has_warnings": warnings, "failure_code": failure_code}})

    def cleanup_events(self, cutoff=None, batch=100):
        with self.transaction() as con:
            ids = [r[0] for r in con.execute("SELECT id FROM research_runs WHERE history_available=1 AND finished_at IS NOT NULL AND events_expire_at<=? LIMIT ?", (cutoff or now(), batch))]
            for run_id in ids:
                con.execute("DELETE FROM research_events WHERE run_id=?", (run_id,))
                con.execute("UPDATE research_runs SET history_available=0 WHERE id=?", (run_id,))
            con.execute("DELETE FROM sessions WHERE expires_at<=?", (now(),))
            con.execute("DELETE FROM login_attempts WHERE expires_at<=?", (now(),))
            return len(ids)


EVENT_FIELDS = {
    "stage.started": {"label", "stage"}, "stage.completed": {"label", "stage", "outcome", "status"},
    "research.dispatched": {"topic", "label", "stage"}, "research.started": {"topic", "label", "stage"},
    "research.completed": {"label", "stage", "outcome", "status"},
    "artifact.created": {"id", "kind", "title", "markdown", "partial", "agent_instance_id", "source_url"},
    "source.discovered": {"url", "title", "query"},
    "quality.evaluated": {"scores", "feedback"}, "critique.created": {"artifact_id", "title"},
    "research.warning": {"message", "code"},
}


def normalize_event(event):
    """Only the deliberately public contract crosses the persistence/API boundary."""
    if not isinstance(event, dict) or event.get("type") not in EVENT_FIELDS:
        return None
    event_type = event["type"]
    raw = event.get("payload") or {}
    if not isinstance(raw, dict):
        return None
    payload = {k: raw[k] for k in EVENT_FIELDS[event_type] if k in raw}
    if "status" in payload and (not isinstance(payload["status"], str) or payload["status"] not in {"completed", "failed", "skipped", "interrupted"}):
        payload.pop("status")
    for key in tuple(payload):
        if key not in {"scores", "partial"} and not isinstance(payload[key], str):
            payload.pop(key)
    if "partial" in payload:
        payload["partial"] = bool(payload["partial"])
    if event_type == "artifact.created" and not payload.get("markdown"):
        return None
    if event_type == "source.discovered" and not str(payload.get("url", "")).startswith(("https://", "http://")):
        return None
    if event_type == "quality.evaluated":
        scores = payload.get("scores", {})
        payload["scores"] = {str(k): v for k, v in scores.items() if isinstance(v, (int, float)) and math.isfinite(v)} if isinstance(scores, dict) else {}
        payload["feedback"] = str(payload.get("feedback", ""))
    result = {"type": event_type, "payload": payload}
    for key in ("agent_instance_id", "parent_instance_id", "tool_call_id"):
        if isinstance(event.get(key), str):
            result[key] = event[key][:200]
    if isinstance(event.get("iteration"), int):
        result["iteration"] = event["iteration"]
    return result
