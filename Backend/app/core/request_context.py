# app/core/request_context.py
from __future__ import annotations

from fastapi import Request


def get_authenticated_username(request: Request) -> str | None:
    payload = getattr(request.state, "user", None)
    if not isinstance(payload, dict):
        return None
    username = payload.get("username")
    if isinstance(username, str) and username.strip():
        return username.strip()
    return None