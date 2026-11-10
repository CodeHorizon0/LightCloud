from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.core.auth_helper import AccessToken
from app.core.services import get_services
from app.models import User
from app.services.storage import UserStorage

COOKIE_NAME = "access_token"


@dataclass(frozen=True, slots=True)
class Session:
    user: User
    token: AccessToken


async def current_session_user(request: Request, session: Session) -> User | None:
    if session.token.expires_at <= time():
        return None
    user = await get_services(request).database.get_session_user(session.token)
    if (
        user is None
        or user.token_version != session.token.version
        or user.username != session.token.username
    ):
        return None
    return user


async def session_is_active(request: Request, session: Session) -> bool:
    return await current_session_user(request, session) is not None


@asynccontextmanager
async def session_storage(
    request: Request, session: Session, *, create: bool = False
) -> AsyncIterator[UserStorage]:
    manager = get_services(request).storage
    storage = manager.for_user(session.user)
    async with storage.lock():
        if not await session_is_active(request, session):
            raise HTTPException(401, "Invalid session")
        await manager.prepare(storage, session.user, create=create)
        yield storage


async def require_session(request: Request) -> Session:
    raw_token = request.cookies.get(COOKIE_NAME)
    if not raw_token:
        raise HTTPException(401, "Not authenticated")

    if len(raw_token) > 4096:
        raise HTTPException(401, "Invalid token")

    token, status = get_services(request).tokens.verify(raw_token)
    if token is None:
        if status == "expired":
            raise HTTPException(
                401,
                {"detail": "Token expired", "code": "token_expired", "redirect_to": "/login"},
                headers={"X-Auth-Redirect": "/login"},
            )
        raise HTTPException(401, "Invalid token")

    user = await get_services(request).database.get_session_user(token)
    if user is None or user.username != token.username:
        raise HTTPException(401, "Invalid session")
    if user.token_version != token.version:
        raise HTTPException(
            401,
            {"detail": "Token version invalid, please re-login", "code": "token_version_mismatch"},
            headers={"X-Auth-Redirect": "/login"},
        )
    return Session(user, token)


Authenticated = Annotated[Session, Depends(require_session)]
