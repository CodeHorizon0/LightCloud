from __future__ import annotations

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.settings import Settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
JSON_BODY_LIMIT = 2 * 1024 * 1024


class RequestProtectionMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if scope["method"] not in SAFE_METHODS:
            origin = headers.get("origin")
            host = headers.get("host")
            same_origin = f"{scope['scheme']}://{host}" if host else None
            if (
                origin is not None
                and origin != same_origin
                and origin not in self.settings.cors.allow_origins
            ) or (origin is None and headers.get("sec-fetch-site") == "cross-site"):
                await JSONResponse({"detail": "Untrusted request origin"}, 403)(
                    scope, receive, send
                )
                return

        limit = JSON_BODY_LIMIT
        if scope["method"] == "POST" and scope["path"].rstrip("/") in {"/upload", "/sync/upload"}:
            limit = (
                self.settings.max_batch_size
                + self.settings.max_upload_files * 16 * 1024
                + 128 * 1024
            )

        length = headers.get("content-length")
        if length is not None:
            if not length.isascii() or not length.isdecimal():
                await JSONResponse({"detail": "Invalid Content-Length"}, 400)(scope, receive, send)
                return
            if len(length) > 20 or int(length) > limit:
                await JSONResponse({"detail": "Request body too large"}, 413)(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(413, "Request body too large")
            return message

        await self.app(scope, limited_receive, send)
