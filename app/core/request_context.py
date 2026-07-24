from __future__ import annotations

from fastapi import Request

from app.core.auth_helper import verify_access_token


def get_authenticated_username(request: Request) -> str | None:
    payload = getattr(request.state, "user", None)
    if not isinstance(payload, dict):
        token = request.cookies.get("access_token")
        if token:
            payload = verify_access_token(token)

    if isinstance(payload, dict):
        username = payload.get("sub") or payload.get("username") or payload.get("email")
        if isinstance(username, str) and username.strip():
            return username.strip()

    return None
