from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import secrets
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .db import Database
from .delivery_api import install_delivery_api
from .delivery_schema import SCHEMA_VERSION
from .local_session import LocalSession
from .models import BatchReviewUpdate, DecoderMessage, ReportRequest, ReviewUpdate, RuleSettingsUpdate
from .platforms.factory import create_platform_services
from .service import OrganizerService, ReviewConflict


STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None, *, start_analysis_worker: bool = True, local_session: LocalSession | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    session = local_session
    if session is None and app_settings.runtime_platform == 'windows':
        session = LocalSession(app_settings.database_path.parent / 'private' / 'session', app_settings.port)
    database = Database(app_settings.database_path)
    database.initialize()
    service = OrganizerService(database, app_settings)
    probe, listener = create_platform_services(app_settings, service)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if start_analysis_worker:
            await app.state.ai_worker.start()
        try:
            yield
        finally:
            await app.state.ai_worker.stop()
            listener.stop()
            if session:
                session.close()

    app = FastAPI(
        title="交付小助手本地原型",
        version="0.5.7",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.service = service
    app.state.listener = listener
    app.state.probe = probe
    app.state.local_session = session
    instance = os.getenv('WML_INSTANCE_ID', '')
    app.state.instance_id = instance if re.fullmatch(r'[A-Za-z0-9_-]{1,80}', instance) else secrets.token_hex(16)
    install_delivery_api(app, database, service)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        def secure(response):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            return response

        if request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            return secure(JSONResponse(status_code=403, content={"detail": "local access only"}))
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            allowed = {
                f"http://127.0.0.1:{app_settings.port}",
                f"http://localhost:{app_settings.port}",
            }
            file_bootstrap = session is not None and request.url.path == '/api/session/exchange' and origin == 'null'
            if origin and origin not in allowed and not file_bootstrap:
                return secure(JSONResponse(status_code=403, content={"detail": "cross-origin rejected"}))
        if session and (request.url.path.startswith('/api/') or request.url.path == '/openapi.json'):
            if request.url.path not in {'/api/health', '/api/session/exchange'} and not session.authenticated(request.cookies.get(session.cookie_name)):
                return secure(JSONResponse(status_code=401, content={'code':'local_session_required','detail':'请从本机启动入口进入工作台'}))
        response = await call_next(request)
        return secure(response)

    @app.get("/", include_in_schema=False)
    def index(request: Request) -> FileResponse:
        authenticated = session is None or session.authenticated(request.cookies.get(session.cookie_name))
        return FileResponse(STATIC_DIR / ('index.html' if authenticated else 'session-login.html'))

    @app.post('/api/session/exchange', include_in_schema=False)
    async def exchange_session(request: Request):
        if session is None:
            return JSONResponse(status_code=404, content={'detail':'会话入口不可用'})
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/x-www-form-urlencoded':
            return JSONResponse(status_code=415, content={'detail':'会话入口格式不正确'})
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024:
                return JSONResponse(status_code=413, content={'detail':'会话入口格式不正确'})
        try:
            fields = parse_qs(body.decode('utf-8'), strict_parsing=True, max_num_fields=2)
            token = fields['token'][0] if set(fields) == {'token'} and len(fields['token']) == 1 else ''
        except (ValueError, UnicodeError):
            token = ''
        cookie = session.exchange(token)
        if cookie is None:
            return JSONResponse(status_code=403, content={'detail':'会话入口已失效，请重新启动服务'})
        response = RedirectResponse('/', status_code=303)
        response.set_cookie(session.cookie_name, cookie, httponly=True, samesite='strict', path='/')
        return response

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "product": "group-chat-organizer-local-listener",
            "version": app.version,
            "platform": app_settings.runtime_platform,
            "build": "windows-local-20261012" if app_settings.runtime_platform == "windows" else "security-20261012",
            "schema": SCHEMA_VERSION,
            "instance_id": app.state.instance_id,
            "session_required": session is not None,
        }

    @app.get("/api/dashboard")
    def dashboard() -> dict:
        return service.dashboard(probe.inspect()) | {"process": listener.status()}

    @app.get("/api/probe")
    def environment_probe() -> dict:
        return probe.inspect()

    @app.post("/api/listener/start")
    def start_listener() -> dict:
        return listener.start()

    @app.post("/api/listener/stop")
    def stop_listener() -> dict:
        return listener.stop()

    @app.get("/api/settings")
    def get_settings() -> dict:
        return service.get_settings()

    @app.put("/api/settings")
    def update_settings(update: RuleSettingsUpdate) -> dict:
        return service.update_settings(update)

    @app.get("/api/messages")
    def messages(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=10, le=100),
        search: str = Query(default="", max_length=100),
    ) -> dict:
        return service.list_messages(page, page_size, search)

    @app.get("/api/questions")
    def questions(
        question_status: str = Query(
            default="pending", alias="status", pattern="^(pending|confirmed|ignored)$"
        ),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=10, le=100),
    ) -> dict:
        total = service.count_questions(question_status)
        pages = max(1, (total + page_size - 1) // page_size)
        current_page = min(page, pages)
        return {
            "items": service.list_questions(
                question_status, page_size, (current_page - 1) * page_size
            ),
            "total": total,
            "page": current_page,
            "page_size": page_size,
            "pages": pages,
        }

    @app.patch("/api/questions/{question_id}")
    def review(question_id: int, update: ReviewUpdate) -> dict:
        try:
            result = service.review(question_id, update.status, update.expected_version)
        except ReviewConflict as exc:
            raise HTTPException(status_code=409, detail="问题已被其他操作更新") from exc
        if result is None:
            raise HTTPException(status_code=404, detail="问题不存在")
        return result

    @app.post("/api/questions/batch-review")
    def batch_review(update: BatchReviewUpdate) -> dict:
        return service.batch_review(
            [(item.id, item.expected_version) for item in update.items], update.status
        )

    @app.get("/api/reports")
    def reports(limit: int = Query(default=60, ge=1, le=100)) -> dict:
        return {"items": service.list_reports(limit)}

    @app.post("/api/reports/generate")
    def generate_report(request: ReportRequest) -> dict:
        if request.date:
            return service.generate_report(request.date, request.date)
        return service.generate_report(request.start_date, request.end_date)

    @app.delete("/api/reports/id/{report_id}", status_code=204)
    def delete_report_by_id(report_id: int) -> None:
        if not service.delete_report_by_id(report_id):
            raise HTTPException(status_code=404, detail="报告不存在")

    @app.delete("/api/reports/{report_date}", status_code=204)
    def delete_report(report_date: str) -> None:
        try:
            deleted = service.delete_report(report_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="报告日期格式不合法") from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="报告不存在")

    @app.post("/api/demo/messages")
    def demo_messages() -> dict:
        groups = service.get_settings()["groups"]
        group = groups[0]
        now = datetime.now(timezone.utc)
        samples = (
            ("产品经理", "@我 请确认一下本周验收是否会延期？", True),
            ("测试同学", "本机导出报告时报错，麻烦跟进", False),
            ("运营同学", "收到，谢谢", False),
            ("项目负责人", "客户投诉的问题什么时候能答复？", False),
        )
        accepted = 0
        for index, (sender, content, is_at_me) in enumerate(samples):
            result = service.ingest(
                DecoderMessage(
                    source_id=f"demo-{now.timestamp()}-{index}",
                    chat_name=group,
                    sender=sender,
                    content=content,
                    message_type="text",
                    source_time=now,
                    is_group=True,
                    is_at_me=is_at_me,
                    source_kind="demo",
                )
            )
            accepted += int(bool(result.get("accepted")))
        return {"accepted": accepted}

    return app
