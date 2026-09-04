# app/middleware.py
from __future__ import annotations

from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.auth_helper import JWTService
from app.db.database import get_user_by_id


class JWTMiddleware(BaseHTTPMiddleware):
    PUBLIC_PREFIXES = (
        "/auth/register",
        "/auth/login",
    )
    PROTECTED_PREFIXES = (
        "/upload",
        "/download/",
        "/preview/",
        "/delete",
        "/metadata/stream",
        "/auth/me",
        "/auth/logout",
        "/auth/delete",
        "/auth/logout-all",
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

        jwt_service: JWTService = request.app.state.jwt_service
        payload, status = jwt_service.verify_token_with_status(token)
        if not payload:
            if status == "expired":
                return JSONResponse(
                    {"detail": "Token expired", "code": "token_expired", "redirect_to": "/login"},
                    status_code=401,
                    headers={"X-Auth-Redirect": "/login"},
                )
            return JSONResponse({"detail": "Invalid token"}, status_code=401)

        user_id = payload.get("sub")
        username = payload.get("username")
        token_version = payload.get("token_version")

        if not user_id or not username or token_version is None:
            return JSONResponse({"detail": "Invalid token payload"}, status_code=401)

        try:
            user_id_uuid = UUID(user_id)
        except ValueError:
            return JSONResponse({"detail": "Invalid token payload"}, status_code=401)

        db_user = await get_user_by_id(user_id_uuid)
        if db_user is None:
            return JSONResponse({"detail": "User not found"}, status_code=401)

        if db_user["username"] != username:
            return JSONResponse({"detail": "Username mismatch"}, status_code=401)

        if db_user["token_version"] != token_version:
            return JSONResponse(
                {"detail": "Token version invalid, please re-login", "code": "token_version_mismatch"},
                status_code=401,
                headers={"X-Auth-Redirect": "/login"},
            )

        request.state.user = payload
        return await call_next(request)