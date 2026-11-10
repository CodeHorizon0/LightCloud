from __future__ import annotations

import os
import secrets
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from anyio import CapacityLimiter
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.files import router as files_router
from app.api.routes.metadata import router as metadata_router
from app.api.routes.sync import router as sync_router
from app.core.auth_helper import JWTService
from app.core.passwords import PasswordService
from app.core.services import ApplicationServices
from app.core.settings import Settings, load_settings
from app.db.database import UserDatabase
from app.middleware import RequestProtectionMiddleware
from app.services.compression.manager import CompressionManager
from app.services.file_lock import AsyncFileLock
from app.services.sse import EventBroker
from app.services.storage import UserStorageManager


async def _jwt_secret(settings: Settings, locks: Path) -> str:
    if settings.jwt_secret:
        return settings.jwt_secret

    secret_path = locks.parent / ".jwt-secret"
    async with AsyncFileLock(locks / "jwt-secret.lock"):
        if secret_path.exists():
            secret = secret_path.read_text(encoding="ascii").strip()
            if len(secret) < 64:
                raise ValueError("Invalid persisted JWT secret")
            return secret
        secret = secrets.token_urlsafe(64)
        fd, name = tempfile.mkstemp(dir=secret_path.parent, prefix=".secret-")
        try:
            with os.fdopen(fd, "w", encoding="ascii") as output:
                output.write(secret)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, secret_path)
        finally:
            Path(name).unlink(missing_ok=True)
        return secret


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = UserDatabase(settings.database_file)
        try:
            await database.initialize()
            storage = UserStorageManager(settings.storage_dir, database)
            storage.initialize()
            await storage.migrate_all()
            passwords = PasswordService()
            app.state.services = ApplicationServices(
                settings=settings,
                database=database,
                storage=storage,
                tokens=JWTService(
                    await _jwt_secret(settings, storage.locks), settings.jwt_algorithm
                ),
                passwords=passwords,
                dummy_password_hash=await passwords.hash(secrets.token_urlsafe(24)),
                compression=CompressionManager(
                    sample_size=settings.compression.scan_sample_size,
                    min_savings_percent=settings.compression.min_savings_percent,
                    max_source_size=settings.compression.max_source_size,
                ),
                events=EventBroker(),
                uploads=CapacityLimiter(settings.concurrent_uploads),
                previews=CapacityLimiter(2),
                compressed_reads=CapacityLimiter(4),
            )
            yield
        finally:
            await database.close()

    app = FastAPI(title="LightCloud", lifespan=lifespan)

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> Response:
        if isinstance(exc.detail, dict):
            return JSONResponse(exc.detail, exc.status_code, headers=exc.headers)
        return await http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> Response:
        details = [
            {key: error[key] for key in ("type", "loc", "msg") if key in error}
            for error in exc.errors()
        ]
        return JSONResponse({"detail": details}, 422, headers={"Cache-Control": "no-store"})

    app.add_middleware(RequestProtectionMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.allow_origins,
        allow_methods=settings.cors.allow_methods,
        allow_headers=settings.cors.allow_headers,
        allow_credentials=settings.cors.allow_credentials,
        expose_headers=[
            "X-Auth-Redirect",
            "ETag",
            "X-Sync-Account",
            "X-Preview-Quality",
            "X-Preview-Kind",
            "X-File-Revision",
            "X-Preview-Account",
            "Content-Range",
            "Accept-Ranges",
            "Retry-After",
            "Content-Disposition",
        ],
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts, www_redirect=False
    )
    app.include_router(auth_router)
    app.include_router(files_router)
    app.include_router(metadata_router)
    app.include_router(sync_router)
    return app


settings = load_settings()
app = create_app(settings)

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        limit_concurrency=128,
        timeout_graceful_shutdown=10,
    )
