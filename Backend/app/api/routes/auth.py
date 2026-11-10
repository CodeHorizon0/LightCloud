from __future__ import annotations

from datetime import timedelta

from anyio import CancelScope
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.request_context import (
    COOKIE_NAME,
    Authenticated,
    current_session_user,
    session_storage,
)
from app.core.services import get_services
from app.db.database import UserAlreadyExistsError
from app.models import Credentials, PasswordChange, Registration
from app.services.sse import AUTH_CHANGED

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _logout_response(request: Request, message: str) -> JSONResponse:
    settings = get_services(request).settings
    response = JSONResponse({"msg": message}, headers={"Cache-Control": "no-store"})
    response.delete_cookie(
        COOKIE_NAME,
        secure=settings.cookie_secure or request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
    return response


@router.post("/register", status_code=201)
async def register(user: Registration, request: Request) -> dict[str, str]:
    services = get_services(request)
    passwords = services.passwords
    database = services.database
    passwords.check_rate("register", _client_ip(request))
    password_hash = await passwords.hash(user.password)
    try:
        created = await database.create_user(user.username, password_hash)
    except UserAlreadyExistsError as exc:
        raise HTTPException(409, "User already exists") from exc
    return {"id": str(created.id), "username": created.username}


@router.post("/login")
async def login(request: Request, user: Credentials) -> JSONResponse:
    services = get_services(request)
    settings = services.settings
    passwords = services.passwords
    database = services.database
    passwords.check_rate("login", _client_ip(request))
    db_user = await database.get_user(user.username)
    password_hash = db_user.password_hash if db_user else services.dummy_password_hash
    valid = await passwords.verify(user.password, password_hash)
    if db_user is None or not valid:
        raise HTTPException(401, "Invalid credentials")

    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    token = services.tokens.create_access_token(
        db_user.id, db_user.username, db_user.token_version, lifetime
    )
    response = JSONResponse({"msg": "Logged in"}, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure or request.url.scheme == "https",
        max_age=int(lifetime.total_seconds()),
    )
    return response


@router.get("/me")
async def me(session: Authenticated) -> JSONResponse:
    return JSONResponse(
        {
            "authenticated": True,
            "user": {"id": str(session.user.id), "username": session.user.username},
        },
        headers={"Cache-Control": "no-store"},
    )


@router.patch("/password")
async def change_password(
    request: Request, payload: PasswordChange, session: Authenticated
) -> JSONResponse:
    services = get_services(request)
    services.passwords.check_rate("password", f"{session.user.id}:{_client_ip(request)}")
    if not await services.passwords.verify(payload.current_password, session.user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(400, "Choose a different new password")
    password_hash = await services.passwords.hash(payload.new_password)
    storage = services.storage.for_user(session.user)
    async with storage.lock():
        with CancelScope(shield=True):
            if await current_session_user(
                request, session
            ) is None or not await services.database.change_password(
                session.token, session.user.password_hash, password_hash
            ):
                raise HTTPException(401, "Session changed. Sign in again.")
            services.events.publish(session.user.id, AUTH_CHANGED)
    return _logout_response(request, "Password changed. Sign in again on your devices.")


@router.post("/logout")
async def logout(request: Request, session: Authenticated) -> JSONResponse:
    services = get_services(request)
    await services.database.revoke_session(session.token)
    services.events.publish(session.user.id, AUTH_CHANGED)
    return _logout_response(request, "Logged out")


@router.post("/logout-all")
async def logout_all(request: Request, session: Authenticated) -> JSONResponse:
    services = get_services(request)
    await services.database.revoke_all(session.token)
    services.events.publish(session.user.id, AUTH_CHANGED)
    return _logout_response(request, "Logged out from all devices")


@router.delete("/delete")
async def delete_account(request: Request, session: Authenticated) -> JSONResponse:
    services = get_services(request)
    async with session_storage(request, session):
        await services.database.delete_user(session.user.id)
        services.events.publish(session.user.id, AUTH_CHANGED)
        await services.storage.purge(session.user.id)
    return _logout_response(request, "Account deleted")
