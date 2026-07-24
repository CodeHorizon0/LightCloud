from __future__ import annotations

import asyncio
import gc
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.files import router as files_router
from app.api.routes.metadata import router as metadata_router
from app.core import auth_helper
from app.core.settings import load_settings
from app.db.database import init_db
from app.middleware import JWTMiddleware
from app.services.compression.manager import CompressionManager
from app.services.storage import UserStorageManager

settings = load_settings()

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    auth_helper.set_secret_key(settings.jwt_secret)
    auth_helper.set_algorithm(settings.jwt_algorithm)

    app.state.settings = settings
    app.state.storage_manager = UserStorageManager(settings.storage_dir)
    app.state.compression_manager = CompressionManager(
        settings.storage_dir / "_compression_jobs",
        sample_size=settings.compression_scan_sample_size,
        min_savings_percent=settings.compression_min_savings_percent,
        max_source_size=settings.compression_max_source_size,
    )
    app.state.sse_clients = {}
    app.state.sse_lock = None

    app.state.last_request_time = time.time()
    app.state.is_idle = False

    await init_db()

    idle_task = asyncio.create_task(idle_cleanup_task(app))

    try:
        yield
    finally:
        idle_task.cancel()
        await idle_task
        print("[shutdown] Shutdown complete.")

# Idle handler
async def idle_cleanup_task(app: FastAPI):
    settings = app.state.settings
    threshold = settings.idle_threshold_seconds
    interval = settings.idle_check_interval_seconds

    while True:
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            print("[idle] Idle cleanup task cancelled, exiting.")
            break

        now = time.time()
        idle_time = now - app.state.last_request_time

        if idle_time > threshold and not app.state.is_idle:
            print(f"[idle] Entering idle sleep mode (no requests for {idle_time:.0f}s)")
            gc.collect(2)
            gc.collect(2)
            app.state.is_idle = True
            print("[idle] Memory cleanup completed")
        elif idle_time <= threshold and app.state.is_idle:
            pass

# === FastAPI init
app = FastAPI(title="LightCloud", lifespan=lifespan)

# Idle middleware
@app.middleware("http")
async def activity_middleware(request: Request, call_next):
    if app.state.is_idle:
        print("[idle] Exiting idle sleep mode (new request received)")
        app.state.is_idle = False
    app.state.last_request_time = time.time()
    return await call_next(request)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
    allow_credentials=True,
)
app.add_middleware(JWTMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=settings.gzip_minimum_size)

# Routes
app.include_router(auth_router)
app.include_router(files_router)
app.include_router(metadata_router)

# Uvicorn run
if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        reload=False,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=5,
        log_level="info",
    )