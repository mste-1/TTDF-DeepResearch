"""HTTP and durable state invariants; no model/search calls."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from server.app import COOKIE, create_app
from server.config import Settings
from server.db import Database, later, now
from server.errors import ServiceError

PASSWORD = "initial-password-123"
NEW_PASSWORD = "different-password-456"
ORIGIN = "http://testserver"


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(data_dir=Path(self.temp.name), secure_cookies=False,
                                 allowed_origins=(ORIGIN,), require_safe_sqlite=False)
        self.app = create_app(self.settings)
        self.client = TestClient(self.app).__enter__()
        self.database = self.app.state.database
        self.user_id = self.database.create_user("alice", PASSWORD)
        self.other_id = self.database.create_user("bob", PASSWORD, must_change_password=False)
        self.admin_id = self.database.create_user("admin", PASSWORD, "admin", must_change_password=False)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self, username="alice", password=PASSWORD, client=None):
        client = client or self.client
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}

    def ready_user(self):
        headers = self.login()
        response = self.client.post("/api/v1/auth/change-password", json={"old_password": PASSWORD, "new_password": NEW_PASSWORD}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return headers

    def create(self, headers, **kwargs):
        return self.client.post("/api/v1/research-runs", json={"topic": "研究城市交通", **kwargs},
                                headers={**headers, "Idempotency-Key": str(uuid.uuid4())})

    def test_first_password_forced_csrf_origin_and_rotation(self):
        headers = self.login()
        old_cookie = self.client.cookies.get(COOKIE)
        self.assertEqual(self.create(headers).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/research-runs").json()["code"], "PASSWORD_CHANGE_REQUIRED")
        bad = self.client.post("/api/v1/auth/change-password", json={"old_password": PASSWORD, "new_password": NEW_PASSWORD}, headers={"Origin": ORIGIN})
        self.assertEqual(bad.json()["code"], "CSRF_REJECTED")
        changed = self.client.post("/api/v1/auth/change-password", json={"old_password": PASSWORD, "new_password": NEW_PASSWORD}, headers=headers)
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(old_cookie, self.client.cookies.get(COOKIE))
        self.assertFalse(changed.json()["user"]["must_change_password"])
        headers["X-CSRF-Token"] = changed.json()["csrf_token"]
        self.assertEqual(self.create(headers).status_code, 202)
        self.assertEqual(self.create({**headers, "Origin": "https://evil.example"}).status_code, 403)
        old = self.client.get("/api/v1/auth/me", headers={"Cookie": f"{COOKIE}={old_cookie}"})
        self.assertEqual(old.status_code, 401)
        self.assertIn("httponly", changed.headers["set-cookie"].lower())
        self.assertIn("samesite=lax", changed.headers["set-cookie"].lower())

    def test_account_isolation_and_admin_read_only(self):
        owner_headers = self.ready_user()
        run = self.create(owner_headers).json()
        self.login("bob")
        for path in ("", "/events", "/events/history", "/report.md", "/artifacts/example.md"):
            self.assertEqual(self.client.get(f"/api/v1/research-runs/{run['id']}{path}").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/research-runs?scope=all").status_code, 403)
        admin_headers = self.login("admin")
        self.assertEqual(self.client.get(f"/api/v1/research-runs/{run['id']}").status_code, 200)
        self.assertEqual(len(self.client.get("/api/v1/research-runs?scope=all").json()["items"]), 1)
        self.assertEqual(self.client.post(f"/api/v1/research-runs/{run['id']}/cancel", headers=admin_headers).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/v1/research-runs/{run['id']}", headers=admin_headers).status_code, 404)

    def test_idempotency_capacity_and_repeat_topic(self):
        self.database.settings = replace(self.settings, daily_research_limit=100)
        headers = {**self.ready_user(), "Idempotency-Key": "stable-submit-123"}
        first = self.client.post("/api/v1/research-runs", json={"topic": "主题"}, headers=headers)
        duplicate = self.client.post("/api/v1/research-runs", json={"topic": "主题"}, headers=headers)
        self.assertEqual(first.json()["id"], duplicate.json()["id"])
        self.assertEqual(self.client.post("/api/v1/research-runs", json={"topic": "其他主题"}, headers=headers).status_code, 409)
        for _ in range(9):
            self.assertEqual(self.create(headers, topic="主题").status_code, 202)
        full = self.create(headers)
        self.assertEqual(full.status_code, 429)
        self.assertEqual(full.json()["code"], "QUEUE_FULL")
        self.assertEqual(self.client.post("/api/v1/research-runs", json={"topic": "主题"}, headers=headers).json()["id"], first.json()["id"])

    def test_concurrent_admission_never_exceeds_ten(self):
        self.database.settings = replace(self.settings, daily_research_limit=100)
        user = {"id": self.user_id, "role": "user"}
        def submit(index):
            try:
                return self.database.create_run(user, str(index), "", f"submit-{index:08d}")["id"]
            except ServiceError as exc:
                self.assertEqual(exc.code, "QUEUE_FULL")
                return None
        with ThreadPoolExecutor(max_workers=16) as executor:
            results = list(executor.map(submit, range(25)))
        self.assertEqual(sum(x is not None for x in results), 10)

    def test_daily_limit_returns_actionable_error_and_replays_accepted_request(self):
        headers = {**self.ready_user(), "Idempotency-Key": "daily-submit-123"}
        first = self.client.post("/api/v1/research-runs", json={"topic": "主题"}, headers=headers)
        self.assertEqual(first.status_code, 202)
        for _ in range(4):
            self.assertEqual(self.create(headers).status_code, 202)
        rejected = self.create(headers)
        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(rejected.json()["code"], "DAILY_RESEARCH_LIMIT")
        self.assertIn("5 次", rejected.json()["message"])
        self.assertIn("北京时间", rejected.json()["message"])
        self.assertFalse(rejected.json()["retryable"])
        replay = self.client.post("/api/v1/research-runs", json={"topic": "主题"}, headers=headers)
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json()["id"], first.json()["id"])

    def test_queued_cancel_and_fresh_retry(self):
        headers = self.ready_user()
        run = self.create(headers).json()
        stopped = self.client.post(f"/api/v1/research-runs/{run['id']}/cancel", headers=headers).json()
        self.assertEqual(stopped["status"], "cancelled")
        again = self.client.post(f"/api/v1/research-runs/{run['id']}/cancel", headers=headers).json()
        self.assertEqual(again["finished_at"], stopped["finished_at"])
        new = self.create(headers, retry_of=run["id"]).json()
        self.assertNotEqual(new["id"], run["id"])
        self.assertEqual(new["artifacts"], [])
        self.assertEqual(self.client.delete(f"/api/v1/research-runs/{new['id']}", headers=headers).status_code, 409)
        self.assertEqual(self.client.delete(f"/api/v1/research-runs/{run['id']}", headers=headers).status_code, 204)

    def test_daily_quota_exemption_uses_authenticated_admin_role(self):
        user_headers = self.login("bob")
        for _ in range(5):
            self.assertEqual(self.create(user_headers).status_code, 202)
        forged = self.create(user_headers, role="admin", user_id=self.admin_id)
        self.assertEqual(forged.status_code, 429)
        self.assertEqual(forged.json()["code"], "DAILY_RESEARCH_LIMIT")
        admin_headers = self.login("admin")
        for _ in range(6):
            created = self.create(admin_headers)
            self.assertEqual(created.status_code, 202, created.text)
            self.assertEqual(created.json()["user_id"], self.admin_id)
            cancelled = self.client.post(f"/api/v1/research-runs/{created.json()['id']}/cancel", headers=admin_headers)
            self.assertEqual(cancelled.status_code, 200)
        with self.database.read() as con:
            self.assertEqual(con.execute("SELECT SUM(submissions) FROM research_daily_usage").fetchone()[0], 5)
        rejected = self.create(self.login("bob"))
        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(rejected.json()["code"], "DAILY_RESEARCH_LIMIT")

    def test_artifact_snapshot_sse_retention_and_source_boundary(self):
        headers = self.ready_user()
        run = self.create(headers).json()
        execution = self.database.claim("test-manager")["execution_id"]
        self.database.ingest(run["id"], execution, {"type": "stage.started", "agent_instance_id": "writer-1", "payload": {"label": "成稿", "stage": "final", "origin": "reasoning_fallback"}})
        self.database.ingest(run["id"], execution, {"type": "artifact.created", "agent_instance_id": "writer-1", "payload": {
            "id": "draft-1", "kind": "final", "title": "报告", "markdown": "# 部分结果", "partial": True, "origin": "reasoning_fallback"}})
        self.database.ingest(run["id"], execution, {"type": "artifact.created", "agent_instance_id": "writer-1", "payload": {
            "id": "draft-1", "kind": "final", "title": "报告", "markdown": "# 已完成结果", "partial": False}})
        self.database.ingest(run["id"], execution, {"type": "artifact.created", "agent_instance_id": "writer-1", "payload": {
            "id": "draft-1", "kind": "final", "title": "迟到的片段", "markdown": "不能倒退", "partial": True}})
        preserved_complete = self.client.get(f"/api/v1/research-runs/{run['id']}/artifacts/draft-1").json()
        self.assertFalse(preserved_complete["partial"])
        self.assertEqual(preserved_complete["markdown"], "# 已完成结果")
        self.database.ingest(run["id"], execution, {"type": "source.discovered", "payload": {"url": "https://example.com", "title": "来源", "query": "交通", "reasoning_content": "internal"}})
        self.database.finish(run["id"], execution, "completed", "# 最终结果\n\n正文")
        detail = self.client.get(f"/api/v1/research-runs/{run['id']}").json()
        self.assertEqual(detail["status"], "completed")
        self.assertFalse(detail["has_warnings"])
        self.assertEqual(len(detail["artifacts"]), 1)
        self.assertEqual(detail["artifacts"][0]["id"], "draft-1")
        self.assertFalse(detail["artifacts"][0]["partial"])
        self.assertNotIn("markdown", detail["artifacts"][0])
        self.assertEqual(self.client.get(f"/api/v1/research-runs/{run['id']}/artifacts/draft-1").json()["markdown"], "# 最终结果\n\n正文")
        history = self.client.get(f"/api/v1/research-runs/{run['id']}/events/history").json()["items"]
        self.assertEqual([e["seq"] for e in history], list(range(1, detail["last_event_seq"] + 1)))
        self.assertNotIn("reasoning_fallback", json.dumps([detail, history]))
        self.assertNotIn("reasoning_content", json.dumps([detail, history]))
        download = self.client.get(f"/api/v1/research-runs/{run['id']}/report.md")
        self.assertEqual(download.text, "# 最终结果\n\n正文")
        streamed = self.client.get(f"/api/v1/research-runs/{run['id']}/events?after=1", headers={"Last-Event-ID": "3"})
        self.assertEqual(streamed.status_code, 200)
        self.assertIn("id: 4\n", streamed.text)
        self.assertNotIn("id: 3\n", streamed.text)
        self.assertEqual(self.database.cleanup_events(later(detail["finished_at"], days=31)), 1)
        expired = self.client.get(f"/api/v1/research-runs/{run['id']}/events/history")
        self.assertEqual(expired.status_code, 410)
        self.assertIn("history_truncated", self.client.get(f"/api/v1/research-runs/{run['id']}/events").text)
        preserved = self.client.get(f"/api/v1/research-runs/{run['id']}").json()
        self.assertEqual(preserved["artifacts"], detail["artifacts"])
        self.assertEqual(preserved["snapshot"], detail["snapshot"])
        self.assertEqual(preserved["sources"], detail["sources"])

    def test_cancel_race_preserves_late_result_without_success(self):
        headers = self.ready_user()
        run = self.create(headers).json()
        execution = self.database.claim("test-manager")["execution_id"]
        self.client.post(f"/api/v1/research-runs/{run['id']}/cancel", headers=headers)
        self.database.finish(run["id"], execution, "completed", "研究正文")
        detail = self.client.get(f"/api/v1/research-runs/{run['id']}").json()
        self.assertEqual(detail["status"], "cancelled")
        self.assertEqual(self.client.get(f"/api/v1/research-runs/{run['id']}/artifacts/final-report").json()["markdown"], "研究正文")
        self.assertEqual(self.client.get(f"/api/v1/research-runs/{run['id']}/report").status_code, 409)
        before = detail["last_event_seq"]
        self.database.ingest(run["id"], execution, {"type": "research.warning", "payload": {"message": "late"}})
        self.database.finish(run["id"], execution, "completed", "不能覆盖")
        after = self.client.get(f"/api/v1/research-runs/{run['id']}").json()
        self.assertEqual(after["last_event_seq"], before)
        self.assertEqual(self.client.get(f"/api/v1/research-runs/{run['id']}/artifacts/final-report").json()["markdown"], "研究正文")

    def test_errors_do_not_echo_passwords_and_disable_revokes(self):
        headers = self.ready_user()
        invalid = self.client.post("/api/v1/auth/login", json={"username": "alice", "password": {"secret": "never-echo-me"}}, headers={"Origin": ORIGIN})
        self.assertEqual(invalid.status_code, 422)
        self.assertNotIn("never-echo-me", invalid.text)
        self.assertEqual(set(invalid.json()), {"code", "message", "request_id", "retryable"})
        with self.database.transaction() as con:
            con.execute("UPDATE users SET enabled=0 WHERE id=?", (self.user_id,))
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)

    def test_graph_failures_dataflow_and_evaluation_survive_history_expiry(self):
        headers = self.ready_user()
        run = self.create(headers).json()
        execution = self.database.claim("manager")["execution_id"]
        def event(kind, agent, payload, parent=None):
            self.database.ingest(run["id"], execution, {"type": kind, "agent_instance_id": agent,
                "parent_instance_id": parent, "payload": payload})
        event("stage.started", "supervisor", {"stage": "supervisor", "label": "统筹"})
        event("research.dispatched", "researcher", {"stage": "research", "label": "调研"}, "supervisor")
        event("artifact.created", "researcher", {"id": "research-result", "kind": "research", "title": "子研究成果", "markdown": "已经保存的研究成果", "partial": False}, "supervisor")
        event("research.completed", "researcher", {"stage": "research", "label": "调研"}, "supervisor")
        event("stage.started", "failed-researcher", {"stage": "research", "label": "调研"}, "supervisor")
        event("research.completed", "failed-researcher", {"stage": "research", "label": "调研", "status": "failed"}, "supervisor")
        event("research.dispatched", "empty-researcher", {"stage": "research", "label": "调研"}, "supervisor")
        event("research.completed", "empty-researcher", {"stage": "research", "label": "调研"}, "supervisor")
        event("research.dispatched", "partial-researcher", {"stage": "research", "label": "调研"}, "supervisor")
        event("artifact.created", "partial-researcher", {"id": "partial-result", "kind": "research", "title": "研究片段", "markdown": "尚未完成", "partial": True}, "supervisor")
        event("research.completed", "partial-researcher", {"stage": "research", "label": "调研"}, "supervisor")
        event("stage.started", "red-team", {"stage": "red_team", "label": "审阅"}, "supervisor")
        event("artifact.created", "red-team", {"id": "critique", "kind": "critique", "title": "质疑", "markdown": "证据还需要补充"}, "supervisor")
        event("stage.started", "evaluate", {"stage": "evaluation", "label": "评价"}, "supervisor")
        event("quality.evaluated", "evaluate", {"scores": {"accuracy": 8.5}, "feedback": "证据较充分"}, "supervisor")
        event("research.warning", "supervisor", {"code": "summary_degraded", "message": "一份资料仅保留摘录。"})
        self.database.finish(run["id"], execution, "completed", "报告正文")
        detail = self.client.get(f"/api/v1/research-runs/{run['id']}").json()
        statuses = {node["id"]: node["status"] for node in detail["snapshot"]["nodes"]}
        self.assertEqual(statuses["failed-researcher"], "failed")
        edges = detail["snapshot"]["edges"]
        self.assertTrue(any(e["source"] == "supervisor" and e["target"] == "researcher" and e["label"] == "分发主题" for e in edges))
        self.assertTrue(any(e["source"] == "researcher" and e["target"] == "supervisor" and e["label"] == "返回成果" for e in edges))
        self.assertFalse(any(e["source"] in {"failed-researcher", "empty-researcher", "partial-researcher"} and e["label"] == "返回成果" for e in edges))
        self.assertTrue(any(e["source"] == "red-team" and e["target"] == "supervisor" and e["label"] == "返回质疑" for e in edges))
        self.database.cleanup_events(later(detail["finished_at"], days=31))
        retained = self.database.detail(run["id"], {"id": self.user_id, "role": "user"})
        evaluation = next(a for a in retained["artifacts"] if a["kind"] == "evaluation")
        evaluation_body = self.client.get(f"/api/v1/research-runs/{run['id']}/artifacts/{evaluation['id']}").json()["markdown"]
        self.assertIn("8.5", evaluation_body)
        self.assertIn("证据较充分", evaluation_body)
        self.assertEqual(retained["warnings"], [{"code": "summary_degraded", "message": "一份资料仅保留摘录。"}])

    def test_login_attempt_limit_is_durable(self):
        for _ in range(10):
            response = self.client.post("/api/v1/auth/login", json={"username": "alice", "password": "wrong-password"}, headers={"Origin": ORIGIN})
            self.assertEqual(response.status_code, 401)
        limited = self.client.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}, headers={"Origin": ORIGIN})
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["code"], "LOGIN_RATE_LIMITED")


if __name__ == "__main__":
    unittest.main()
