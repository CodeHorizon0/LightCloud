# main.py
from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth_helper.set_secret_key(settings.jwt_secret)

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

    await init_db()

    try:
        yield
    finally:
        print("[shutdown] Shutdown complete.")


app = FastAPI(title="Light Cloud", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
    allow_credentials=True,
)
app.add_middleware(JWTMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=settings.gzip_minimum_size)

app.include_router(auth_router)
app.include_router(files_router)
app.include_router(metadata_router)


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