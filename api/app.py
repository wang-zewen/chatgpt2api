from __future__ import annotations

import os
from contextlib import asynccontextmanager
from threading import Event

import anyio.to_thread
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api import accounts, ai, image_tasks, system
from api.errors import install_exception_handlers
from api.support import resolve_web_asset, start_limited_account_watcher
from services.backup_service import backup_service
from services.config import config
from services.image_service import start_image_cleanup_scheduler

# 同步路由、生图轮询和流式响应都跑在 anyio 线程池里；默认 40 个线程容易被长时间的
# 生图请求占满，导致页面、登录等请求一起排队超时。
DEFAULT_THREADPOOL_SIZE = 200

# 带内容哈希的构建产物可以长期缓存；HTML 和 RSC 数据必须每次校验，
# 否则升级镜像后浏览器会拿旧页面去加载已不存在的 chunk。
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
REVALIDATE_CACHE_CONTROL = "no-cache"


def _threadpool_size() -> int:
    try:
        return max(40, int(os.getenv("CHATGPT2API_THREADPOOL_SIZE") or DEFAULT_THREADPOOL_SIZE))
    except ValueError:
        return DEFAULT_THREADPOOL_SIZE


def _web_cache_control(full_path: str) -> str:
    if full_path.strip("/").startswith("_next/static/"):
        return IMMUTABLE_CACHE_CONTROL
    return REVALIDATE_CACHE_CONTROL


def create_app() -> FastAPI:
    app_version = config.app_version

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        anyio.to_thread.current_default_thread_limiter().total_tokens = _threadpool_size()
        stop_event = Event()
        thread = start_limited_account_watcher(stop_event)
        cleanup_thread = start_image_cleanup_scheduler(stop_event)
        backup_service.start()
        config.cleanup_old_images()
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=1)
            cleanup_thread.join(timeout=1)
            backup_service.stop()

    app = FastAPI(title="chatgpt2api", version=app_version, lifespan=lifespan)
    install_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(ai.create_router())
    app.include_router(accounts.create_router())
    app.include_router(image_tasks.create_router())
    app.include_router(system.create_router(app_version))

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_web(full_path: str):
        asset = resolve_web_asset(full_path)
        if asset is not None:
            return FileResponse(asset, headers={"Cache-Control": _web_cache_control(full_path)})
        if full_path.strip("/").startswith("_next/"):
            raise HTTPException(status_code=404, detail="Not Found")
        fallback = resolve_web_asset("")
        if fallback is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(fallback, headers={"Cache-Control": REVALIDATE_CACHE_CONTROL})

    return app
