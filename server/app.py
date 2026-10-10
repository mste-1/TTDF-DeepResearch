"""HTTP/SSE API; research execution belongs exclusively to server.worker."""
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import sqlite3
import time
from typing import Literal

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException

from server.auth import hash_password, new_tokens, public_user, token_hash, verify_password
from server.config import Settings
from server.db import Database, SCHEMA_VERSION, TERMINAL, later, now, uid
from server.errors import ServiceError

COOKIE = "wenli_session"
DUMMY_PASSWORD = hash_password("unusable-dummy-password-for-timing")


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=10, max_length=1024)


class ResearchInput(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    instructions: str = Field(default="", max_length=10000)
    retry_of: str | None = Field(default=None, max_length=100)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings)

    @asynccontextmanager
    async def lifespan(_app):
        database.initialize()
        yield

    app = FastAPI(title="问砺 API", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.database, app.state.settings = database, settings

    def error_body(request, exc):
        return {"code": exc.code, "message": exc.message,
                "request_id": getattr(request.state, "request_id", uid()), "retryable": exc.retryable}

    @app.middleware("http")
    async def request_context(request, call_next):
        request.state.request_id = uid()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return JSONResponse(error_body(request, exc), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, _exc):
        return JSONResponse(error_body(request, ServiceError("VALIDATION_ERROR", "请求参数不正确，请检查输入。", 422)), status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, _exc):
        return JSONResponse(error_body(request, ServiceError("STORAGE_UNAVAILABLE", "服务暂时不可用，请稍后重试。", 503, True)), status_code=503)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(error_body(request, ServiceError("NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR", "请求的资源不可用。", exc.status_code)), status_code=exc.status_code)

    def origin_check(request: Request):
        if request.headers.get("origin", "").rstrip("/") not in settings.allowed_origins:
            raise ServiceError("ORIGIN_REJECTED", "请求来源不被允许。", 403)

    def session_user(request: Request):
        token = request.cookies.get(COOKIE)
        if not token or len(token) > 200:
            raise ServiceError("UNAUTHENTICATED", "请先登录。", 401)
        with database.read() as con:
            row = con.execute("""SELECT u.*,s.csrf_token,s.token_hash FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1""", (token_hash(token), now())).fetchone()
            if not row:
                raise ServiceError("UNAUTHENTICATED", "登录已失效，请重新登录。", 401)
            return dict(row)

    def research_user(user=Depends(session_user)):
        if user["must_change_password"]:
            raise ServiceError("PASSWORD_CHANGE_REQUIRED", "请先修改初始密码。", 403)
        return user

    def mutation_check(request: Request, user):
        origin_check(request)
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), user["csrf_token"]):
            raise ServiceError("CSRF_REJECTED", "会话校验失败，请刷新页面后重试。", 403)

    def write_user(request: Request, user=Depends(research_user)):
        mutation_check(request, user)
        return user

    def set_cookie(response, token):
        response.set_cookie(COOKIE, token, max_age=settings.session_hours * 3600, httponly=True,
                            secure=settings.secure_cookies, samesite="lax", path="/")

    def create_session(con, user_id):
        token, csrf = new_tokens()
        con.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES(?,?,?,?)",
                    (token_hash(token), user_id, csrf, later(now(), hours=settings.session_hours)))
        return token, csrf

    @app.post("/api/v1/auth/login")
    def login(body: Credentials, request: Request, response: Response):
        origin_check(request)
        ip = request.client.host if request.client else "unknown"
        keys = ("ip:" + ip, "user:" + body.username)
        with database.transaction() as con:
            for key in keys:
                attempt = con.execute("SELECT * FROM login_attempts WHERE key=? AND expires_at>?", (key, now())).fetchone()
                if attempt and attempt["attempts"] >= 10:
                    raise ServiceError("LOGIN_RATE_LIMITED", "登录尝试过多，请 15 分钟后重试。", 429, True)
            for key in keys:
                # Reserve attempts under the same lock before expensive password work.
                con.execute("""INSERT INTO login_attempts(key,attempts,expires_at) VALUES(?,1,?)
                    ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN expires_at>? THEN attempts+1 ELSE 1 END,
                    expires_at=CASE WHEN expires_at>? THEN expires_at ELSE excluded.expires_at END""",
                    (key, later(now(), minutes=15), now(), now()))
            user = con.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
        valid = verify_password(body.password, user["password_hash"] if user else DUMMY_PASSWORD)
        if not valid or not user or not user["enabled"]:
            raise ServiceError("LOGIN_FAILED", "账号或密码不正确。", 401)
        with database.transaction() as con:
            # Reset/disable may race the password calculation; recheck under the write lock.
            fresh = con.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            if not fresh["enabled"] or fresh["password_hash"] != user["password_hash"]:
                raise ServiceError("LOGIN_FAILED", "账号或密码不正确。", 401)
            con.execute("DELETE FROM login_attempts WHERE key=?", ("user:" + body.username,))
            con.execute("UPDATE login_attempts SET attempts=MAX(0,attempts-1) WHERE key=?", ("ip:" + ip,))
            old_cookie = request.cookies.get(COOKIE)
            if old_cookie:
                con.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(old_cookie),))
            token, csrf = create_session(con, user["id"])
        set_cookie(response, token)
        return {"user": public_user(user), "csrf_token": csrf}

    @app.get("/api/v1/auth/me")
    def me(user=Depends(session_user)):
        return {"user": public_user(user), "csrf_token": user["csrf_token"]}

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(request: Request, response: Response, user=Depends(session_user)):
        mutation_check(request, user)
        with database.transaction() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))
        response.delete_cookie(COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax")

    @app.post("/api/v1/auth/change-password")
    def change_password(body: PasswordChange, request: Request, response: Response, user=Depends(session_user)):
        mutation_check(request, user)
        if not verify_password(body.old_password, user["password_hash"]):
            raise ServiceError("PASSWORD_MISMATCH", "当前密码不正确。", 400)
        if body.old_password == body.new_password:
            raise ServiceError("PASSWORD_UNCHANGED", "新密码应与当前密码不同。", 400)
        encoded = hash_password(body.new_password)
        with database.transaction() as con:
            changed = con.execute("UPDATE users SET password_hash=?,must_change_password=0,password_changed_at=? WHERE id=? AND password_hash=? AND enabled=1",
                                  (encoded, now(), user["id"], user["password_hash"])).rowcount
            if not changed:
                raise ServiceError("SESSION_CHANGED", "账号状态已改变，请重新登录。", 401)
            con.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            token, csrf = create_session(con, user["id"])
        set_cookie(response, token)
        return {"user": public_user({**user, "must_change_password": False}), "csrf_token": csrf}

    @app.post("/api/v1/research-runs", status_code=202)
    def create_run(body: ResearchInput, user=Depends(write_user), idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128)):
        topic = body.topic.strip()
        if not topic:
            raise ServiceError("TOPIC_EMPTY", "请填写研究主题。", 422)
        return database.create_run(user, topic, body.instructions.strip(), idempotency_key, body.retry_of)

    @app.get("/api/v1/research-runs")
    def list_runs(scope: Literal["mine", "all"] = "mine", cursor: int | None = Query(default=None, ge=1),
                  limit: int = Query(default=30, ge=1, le=100), status: str | None = None,
                  user_id: str | None = None, created_after: str | None = None, created_before: str | None = None,
                  user=Depends(research_user)):
        if scope == "all" and user["role"] != "admin":
            raise ServiceError("FORBIDDEN", "只有管理员可以查看全部研究。", 403)
        clauses, params = [], []
        if scope == "mine":
            clauses.append("user_id=?")
            params.append(user["id"])
        elif user_id:
            clauses.append("user_id=?")
            params.append(user_id)
        if status == "ended":
            clauses.append("status IN ('completed','completed_with_warnings','cancelled','failed','interrupted')")
        elif status == "running":
            clauses.append("status IN ('running','cancelling')")
        elif status:
            clauses.append("status=?")
            params.append(status)
        for condition, value in (("queue_seq<?", cursor),
                                 ("created_at>=?", created_after), ("created_at<=?", created_before)):
            if value is not None:
                clauses.append(condition)
                params.append(value)
        where = " AND ".join(clauses) or "1=1"
        with database.read() as con:
            rows = con.execute(f"SELECT * FROM research_runs WHERE {where} ORDER BY queue_seq DESC LIMIT ?", (*params, limit + 1)).fetchall()
            return {"items": [database.public_run(con, r, detailed=False) for r in rows[:limit]],
                    "next_cursor": rows[limit - 1]["queue_seq"] if len(rows) > limit else None}

    @app.get("/api/v1/research-runs/{run_id}")
    def detail(run_id: str, user=Depends(research_user)):
        return database.detail(run_id, user)

    @app.post("/api/v1/research-runs/{run_id}/cancel")
    def cancel(run_id: str, user=Depends(write_user)):
        return database.cancel(run_id, user)

    @app.delete("/api/v1/research-runs/{run_id}", status_code=204)
    def delete(run_id: str, user=Depends(write_user)):
        database.delete(run_id, user)

    def artifact(run_id, artifact_id, user):
        with database.read() as con:
            database.authorize(con, run_id, user)
            row = con.execute("SELECT * FROM research_artifacts WHERE run_id=? AND id=?", (run_id, artifact_id)).fetchone()
            if not row:
                raise ServiceError("ARTIFACT_UNAVAILABLE", "该阶段成果尚未生成。", 404)
            return database.public_artifact(row)

    @app.get("/api/v1/research-runs/{run_id}/artifacts/{artifact_id}.md")
    def download_artifact(run_id: str, artifact_id: str, user=Depends(research_user)):
        item = artifact(run_id, artifact_id, user)
        prefix = "> 阶段成果（未完成）\n\n" if item["partial"] else "> 阶段成果\n\n"
        filename = f"wenli-{run_id[:8]}-{'partial-' if item['partial'] else ''}artifact-v{item['version']}.md"
        return Response(prefix + item["markdown"], media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/api/v1/research-runs/{run_id}/artifacts/{artifact_id}")
    def get_artifact(run_id: str, artifact_id: str, user=Depends(research_user)):
        return artifact(run_id, artifact_id, user)

    def report(run_id, user):
        with database.read() as con:
            run = database.authorize(con, run_id, user)
            if run["status"] not in {"completed", "completed_with_warnings"}:
                raise ServiceError("REPORT_UNAVAILABLE", "最终报告尚不可用，可查看已保存的阶段成果。", 409)
            row = con.execute("SELECT markdown FROM research_artifacts WHERE run_id=? AND kind='final' AND partial=0 ORDER BY updated_at DESC LIMIT 1", (run_id,)).fetchone()
            if not row:
                raise ServiceError("REPORT_UNAVAILABLE", "最终报告尚不可用。", 409)
            return {"markdown": row[0], "status": run["status"], "has_warnings": bool(run["has_warnings"])}

    @app.get("/api/v1/research-runs/{run_id}/report.md")
    def download_report(run_id: str, user=Depends(research_user)):
        return Response(report(run_id, user)["markdown"], media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="wenli-{run_id[:8]}.md"'})

    @app.get("/api/v1/research-runs/{run_id}/report")
    def get_report(run_id: str, user=Depends(research_user)):
        return report(run_id, user)

    def read_events(run_id, user, after, limit=100):
        with database.read() as con:
            run = database.authorize(con, run_id, user)
            if not run["history_available"]:
                raise ServiceError("HISTORY_EXPIRED", "详细过程已过期，成果与协作图仍可查看。", 410)
            if after > run["last_event_seq"]:
                raise ServiceError("CURSOR_INVALID", "事件游标无效，请重新获取任务快照。", 400)
            events = [json.loads(r[0]) for r in con.execute(
                "SELECT data FROM research_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?", (run_id, after, limit))]
            return events, run["status"], run["last_event_seq"]

    @app.get("/api/v1/research-runs/{run_id}/events/history")
    def history(run_id: str, after: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500), user=Depends(research_user)):
        events, _status, last = read_events(run_id, user, after, limit)
        end = events[-1]["seq"] if events else after
        return {"items": events, "next_cursor": end if end < last else None, "history_available": True}

    @app.get("/api/v1/research-runs/{run_id}/events")
    async def stream(run_id: str, request: Request, after: int = Query(default=0, ge=0), user=Depends(research_user)):
        header = request.headers.get("last-event-id")
        if header:
            try:
                after = max(after, int(header))
            except ValueError as exc:
                raise ServiceError("CURSOR_INVALID", "事件游标无效。", 400) from exc
        # Authorize before response headers; expired history has a specific stream event.
        database.detail(run_id, user)

        async def messages():
            cursor, heartbeat = after, time.monotonic()
            while not await request.is_disconnected():
                try:
                    current = research_user(session_user(request))
                    events, status, last = read_events(run_id, current, cursor)
                except ServiceError as exc:
                    name = "history_truncated" if exc.code == "HISTORY_EXPIRED" else "stream_error"
                    yield f"event: {name}\ndata: {json.dumps(error_body(request, exc), ensure_ascii=False)}\n\n"
                    return
                for event in events:
                    cursor = event["seq"]
                    yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if status in TERMINAL and cursor >= last:
                    return
                if time.monotonic() - heartbeat >= 15:
                    heartbeat = time.monotonic()
                    yield ": heartbeat\n\n"
                if cursor >= last:
                    await asyncio.sleep(0.7)

        return StreamingResponse(messages(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"})

    @app.get("/api/v1/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/api/v1/health/ready")
    def ready(response: Response):
        with database.read() as con:
            migration = con.execute("PRAGMA user_version").fetchone()[0]
            manager = con.execute("SELECT * FROM manager_state WHERE id=1").fetchone()
            slots = [dict(r) for r in con.execute("SELECT id,state FROM worker_slots ORDER BY id")]
        healthy = bool(manager and manager["healthy"] and manager["heartbeat_at"] >= later(now(), seconds=-30))
        if not healthy or migration != SCHEMA_VERSION:
            response.status_code = 503
        return {"status": "ok" if healthy else "unavailable", "database": "ok", "schema_version": migration,
                "worker": {"healthy": healthy, "slots": slots}}

    return app


app = create_app()
