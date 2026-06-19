from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.auth_helper import verify_access_token_with_status


class JWTMiddleware(BaseHTTPMiddleware):
    PUBLIC_PREFIXES = (
        "/auth/register",
        "/auth/login",
        "/auth/me",
        "/auth/logout",
    )

    PROTECTED_PREFIXES = (
        "/upload",
        "/download/",
        "/preview/",
        "/delete",
        "/metadata/",
        "/compression",
    )

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if request.method == "OPTIONS":
            return await call_next(request)

        if path.startswith(self.PUBLIC_PREFIXES):
            return await call_next(request)

        if not path.startswith(self.PROTECTED_PREFIXES):
            return await call_next(request)

        token = request.cookies.get("access_token")
        if not token:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        payload, status = verify_access_token_with_status(token)
        if not payload:
            if status == "expired":
                return JSONResponse(
                    {"detail": "Token expired", "code": "token_expired", "redirect_to": "/login"},
                    status_code=401,
                    headers={"X-Auth-Redirect": "/login"},
                )
            return JSONResponse({"detail": "Invalid token"}, status_code=401)

        request.state.user = payload
        return await call_next(request)
