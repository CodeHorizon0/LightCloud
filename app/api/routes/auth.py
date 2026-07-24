from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.auth_helper import create_access_token, verify_access_token_with_status
from app.core.passwords import verify_password
from app.db.database import create_user, delete_user, get_user
from app.models import UserCreate, UserLogin

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "access_token"

def _get_username_from_payload(payload: dict | None) -> str | None:
    if not payload:
        return None

    username = payload.get("sub") or payload.get("username") 
    if isinstance(username, str) and username.strip():
        return username.strip()

    return None


def _verify_cookie_token(request: Request) -> str:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload, status = verify_access_token_with_status(token)
    username = _get_username_from_payload(payload)

    if not username:
        if status == "expired":
            raise HTTPException(
                status_code=401,
                detail={"code": "token_expired", "redirect_to": "/login"},
            )
        raise HTTPException(status_code=401, detail="Invalid token")

    return username


@router.post("/register")
async def register(user: UserCreate, request: Request):
    existing = await get_user(user.username)
    if existing:
        return JSONResponse(
            {"detail": "User already exists"},
            status_code=400,
        )

    new_user = await create_user(user.username, user.password)
    if not new_user:
        return JSONResponse(
            {"detail": "Failed to create user"},
            status_code=500,
        )

    storage_manager = request.app.state.storage_manager
    await storage_manager.ensure_user_storage(user.username)

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
    if not password_hash or not verify_password(user.password, password_hash):
        return JSONResponse(
            {"detail": "Invalid credentials"},
            status_code=401,
        )

    access_token = create_access_token(
        subject=user.username,
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
    username = _verify_cookie_token(request)

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


@router.delete("/delete")
async def delete_account(request: Request):
    username = _verify_cookie_token(request)

    storage_manager = request.app.state.storage_manager
    storage_deleted = await storage_manager.delete_user_storage(username)
    if not storage_deleted:
        raise HTTPException(status_code=500, detail="Failed to delete user storage")

    deleted = await delete_user(username)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")

    response = JSONResponse({"msg": "Account deleted"}, status_code=200)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
