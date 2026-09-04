# app/api/routes/auth.py
from __future__ import annotations

import asyncio
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.auth_helper import JWTService
from app.core.passwords import verify_password
from app.db.database import UserAlreadyExistsError, create_user, delete_user, get_user, increment_token_version
from app.models import UserCreate, UserLogin

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "access_token"


@router.post("/register")
async def register(user: UserCreate, request: Request):
    existing = await get_user(user.username)
    if existing:
        return JSONResponse(
            {"detail": "User already exists"},
            status_code=400,
        )

    try:
        new_user = await create_user(user.username, user.password)
    except UserAlreadyExistsError:
        return JSONResponse(
            {"detail": "User already exists"},
            status_code=409,
        )

    if not new_user:
        return JSONResponse(
            {"detail": "Failed to create user"},
            status_code=500,
        )

    storage_manager = request.app.state.storage_manager
    try:
        await storage_manager.ensure_user_storage(user.username)
    except Exception:
        await delete_user(user.username)
        raise HTTPException(status_code=500, detail="Failed to create user storage")

    return JSONResponse(
        content=jsonable_encoder(new_user),
        status_code=201,
    )


@router.post("/login")
async def login(request: Request, user: UserLogin):
    settings = request.app.state.settings
    db_user = await get_user(user.username)
    if not db_user:
        return JSONResponse(
            {"detail": "Invalid credentials"},
            status_code=401,
        )

    password_hash = db_user.get("password_hash")
    if not password_hash:
        return JSONResponse(
            {"detail": "Invalid credentials"},
            status_code=401,
        )

    is_valid = await asyncio.to_thread(verify_password, user.password, password_hash)
    if not is_valid:
        return JSONResponse(
            {"detail": "Invalid credentials"},
            status_code=401,
        )

    jwt_service: JWTService = request.app.state.jwt_service
    access_token = jwt_service.create_access_token(
        user_id=db_user["id"],
        username=user.username,
        token_version=db_user["token_version"],
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )

    response = JSONResponse({"msg": "Logged in"}, status_code=200)
    response.set_cookie(
        key=COOKIE_NAME,
        value=access_token,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return response


@router.get("/me")
async def me(request: Request):
    payload = getattr(request.state, "user", None)
    if not payload or not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Not authenticated")

    username = payload.get("username")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid user data")

    db_user = await get_user(username)
    if not db_user:
        raise HTTPException(status_code=401, detail="User not found")

    safe_username = db_user.get("username")
    if not safe_username:
        raise HTTPException(status_code=401, detail="Invalid user data")

    return {"authenticated": True, "user": {"username": safe_username}}


@router.post("/logout")
async def logout(request: Request):
    response = JSONResponse({"msg": "Logged out"}, status_code=200)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.post("/logout-all")
async def logout_all(request: Request):
    payload = getattr(request.state, "user", None)
    if not payload or not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Not authenticated")

    username = payload.get("username")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid user data")

    db_user = await get_user(username)
    if not db_user:
        raise HTTPException(status_code=401, detail="User not found")

    await increment_token_version(db_user["id"])
    response = JSONResponse({"msg": "Logged out from all devices"}, status_code=200)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.delete("/delete")
async def delete_account(request: Request):
    payload = getattr(request.state, "user", None)
    if not payload or not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Not authenticated")

    username = payload.get("username")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid user data")

    deleted = await delete_user(username)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")

    storage_manager = request.app.state.storage_manager
    storage_deleted = await storage_manager.delete_user_storage(username)
    if not storage_deleted:
        raise HTTPException(status_code=500, detail="Failed to delete user storage")

    response = JSONResponse({"msg": "Account deleted"}, status_code=200)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response