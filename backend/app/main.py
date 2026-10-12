from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .dres_client import DresAuthError, DresClient, DresError
from .metadata import MetadataStore
from .ratelimit import RateLimiter
from .schemas import (
    ImageMetadataResponse,
    LoginRequest,
    LoginResponse,
    SearchRequest,
    SearchResponse,
    SubmitRequest,
    SubmitResponse,
    TaskResponse,
)
from .search import IndexNotBuiltError, SearchEngine
from .sessions import LocalSession, SessionStore

logger = logging.getLogger("retrieval")

settings = get_settings()


class _TaskCache:
    def __init__(self, ttl_s: float = 2.0):
        self._ttl = ttl_s
        self._value: TaskResponse | None = None
        self._expires_at = 0.0

    def get(self) -> TaskResponse | None:
        if time.time() < self._expires_at:
            return self._value
        return None

    def set(self, value: TaskResponse) -> None:
        self._value = value
        self._expires_at = time.time() + self._ttl


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.using_default_secret:
        logger.warning(
            "SESSION_SECRET is using the insecure dev default; set it via env in production."
        )
    app.state.search_engine = SearchEngine(settings)
    app.state.metadata_store = MetadataStore(settings.metadata_path)
    app.state.dres_client = DresClient(settings)
    app.state.sessions = SessionStore(settings)
    app.state.search_limiter = RateLimiter(settings.rate_limit_per_min)
    app.state.submit_limiter = RateLimiter(settings.rate_limit_per_min)
    app.state.task_cache = _TaskCache()
    app.state.ready = True
    logger.info("Loaded index with %d images", app.state.search_engine.num_images)
    yield
    await app.state.dres_client.aclose()


app = FastAPI(title="Castle5000 Retrieval", lifespan=lifespan)


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status_code)


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    return _error("invalid_request", "Dữ liệu gửi lên không hợp lệ", 422)


@app.exception_handler(HTTPException)
async def on_http_exception(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        return _error(detail["code"], detail["message"], exc.status_code)
    return _error("error", str(detail), exc.status_code)


def _require_session(request: Request) -> LocalSession:
    cookie = request.cookies.get(settings.session_cookie_name)
    session = request.app.state.sessions.resolve(cookie)
    if session is None:
        raise HTTPException(
            401, {"code": "unauthorized", "message": "Chưa đăng nhập hoặc phiên đã hết hạn"}
        )
    return session


@app.get("/health")
async def health(request: Request):
    if not getattr(request.app.state, "ready", False):
        raise HTTPException(503, {"code": "not_ready", "message": "Đang nạp index"})
    return {"status": "ok", "images": request.app.state.search_engine.num_images}


@app.post("/api/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request, response: Response):
    try:
        user = await request.app.state.dres_client.login(req.username, req.password)
    except DresAuthError as exc:
        raise HTTPException(401, {"code": exc.code, "message": exc.message})
    except DresError as exc:
        raise HTTPException(502, {"code": exc.code, "message": exc.message})

    cookie_value = request.app.state.sessions.create(
        dres_session_id=user.session_id,
        dres_user_id=user.id,
        username=user.username,
        role=user.role,
    )
    response.set_cookie(
        settings.session_cookie_name,
        cookie_value,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.session_max_age_s,
    )
    return LoginResponse(username=user.username, role=user.role)


@app.get("/api/me", response_model=LoginResponse)
async def me(request: Request):
    session = _require_session(request)
    return LoginResponse(username=session.username, role=session.role)


@app.post("/api/logout")
async def logout(request: Request, response: Response):
    cookie = request.cookies.get(settings.session_cookie_name)
    session = request.app.state.sessions.resolve(cookie)
    if session is not None:
        await request.app.state.dres_client.logout(session.dres_session_id)
    request.app.state.sessions.destroy(cookie)
    response.delete_cookie(settings.session_cookie_name)
    return {"status": "ok", "description": "logged out"}


@app.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest, request: Request):
    _require_session(request)

    client_ip = request.client.host if request.client else "unknown"
    if not request.app.state.search_limiter.allow(client_ip):
        raise HTTPException(
            429, {"code": "rate_limited", "message": "Tìm kiếm quá nhanh, vui lòng chờ"}
        )

    engine: SearchEngine = request.app.state.search_engine
    results, took_ms = await engine.search(req.query, req.k)
    return SearchResponse(
        results=[
            {"id": r["id"], "score": r["score"], "thumb": f"/thumbs/{r['id']}"} for r in results
        ],
        took_ms=took_ms,
    )


@app.get("/api/task", response_model=TaskResponse)
async def get_task(request: Request):
    session = _require_session(request)

    if not settings.dres_evaluation_id:
        return TaskResponse(running=False)

    cached = request.app.state.task_cache.get()
    if cached is not None:
        return cached

    try:
        task = await request.app.state.dres_client.current_task(
            settings.dres_evaluation_id, session.dres_session_id
        )
        server_time_ms = await request.app.state.dres_client.server_time()
    except DresAuthError:
        request.app.state.sessions.destroy(request.cookies.get(settings.session_cookie_name))
        raise HTTPException(
            401, {"code": "session_expired", "message": "Phiên DRES đã hết hạn, hãy đăng nhập lại"}
        )
    except DresError as exc:
        raise HTTPException(502, {"code": exc.code, "message": exc.message})

    if task is None:
        result = TaskResponse(running=False, server_time_ms=server_time_ms)
    else:
        result = TaskResponse(
            running=True,
            name=task.name,
            task_group=task.task_group,
            task_type=task.task_type,
            duration_s=task.duration_s,
            server_time_ms=server_time_ms,
        )
    request.app.state.task_cache.set(result)
    return result


@app.post("/api/submit", response_model=SubmitResponse)
async def submit(req: SubmitRequest, request: Request):
    session = _require_session(request)

    client_ip = request.client.host if request.client else "unknown"
    if not request.app.state.submit_limiter.allow(client_ip):
        raise HTTPException(
            429, {"code": "rate_limited", "message": "Submit quá nhanh, vui lòng chờ"}
        )

    engine: SearchEngine = request.app.state.search_engine
    if not engine.has_id(req.id):
        raise HTTPException(
            400, {"code": "unknown_id", "message": "ID ảnh không hợp lệ"}
        )

    if not settings.dres_evaluation_id:
        raise HTTPException(
            409, {"code": "no_evaluation", "message": "Chưa cấu hình DRES_EVALUATION_ID"}
        )

    try:
        verdict, message = await request.app.state.dres_client.submit(
            settings.dres_evaluation_id, session.dres_session_id, req.id
        )
    except DresAuthError:
        # Never cache the student's password, so we cannot silently
        # re-login; invalidate the local session and make them log in again.
        request.app.state.sessions.destroy(request.cookies.get(settings.session_cookie_name))
        raise HTTPException(
            401, {"code": "session_expired", "message": "Phiên DRES đã hết hạn, hãy đăng nhập lại"}
        )
    except DresError as exc:
        raise HTTPException(502, {"code": exc.code, "message": exc.message})

    return SubmitResponse(verdict=verdict, message=message)


@app.get("/api/metadata/{image_id}", response_model=ImageMetadataResponse)
async def get_metadata(image_id: str, request: Request):
    _require_session(request)
    engine: SearchEngine = request.app.state.search_engine
    if not engine.has_id(image_id):
        raise HTTPException(404, {"code": "not_found", "message": "Không có ảnh này"})
    store: MetadataStore = request.app.state.metadata_store
    meta = store.get(image_id)
    if meta is None:
        raise HTTPException(404, {"code": "no_metadata", "message": "Không có metadata cho ảnh này"})
    return ImageMetadataResponse(
        owner=meta.owner,
        day=meta.day,
        hour=meta.hour,
        frame=meta.frame,
        classes=meta.classes,
        class_count=meta.class_count,
        description=meta.description,
    )


@app.get("/images/{image_id}")
async def get_image(image_id: str, request: Request):
    _require_session(request)
    engine: SearchEngine = request.app.state.search_engine
    if not engine.has_id(image_id):
        raise HTTPException(404, {"code": "not_found", "message": "Không có ảnh này"})
    path = settings.images_dir / image_id
    if not path.exists():
        raise HTTPException(404, {"code": "not_found", "message": "Không có ảnh này"})
    return FileResponse(path, media_type="image/jpeg")


@app.get("/thumbs/{image_id}")
async def get_thumb(image_id: str, request: Request):
    _require_session(request)
    engine: SearchEngine = request.app.state.search_engine
    if not engine.has_id(image_id):
        raise HTTPException(404, {"code": "not_found", "message": "Không có ảnh này"})
    path = settings.thumbs_dir / image_id
    if not path.exists():
        raise HTTPException(404, {"code": "not_found", "message": "Không có ảnh này"})
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


_frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
