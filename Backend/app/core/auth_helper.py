# app/core/auth_helper.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from jose import ExpiredSignatureError, JWTError, jwt

_SECRET_KEY: str | None = None
_ALGORITHM: str | None = None
_ISSUER: str = "lc-backend"
_AUDIENCE: str = "lc-api-user"


def set_secret_key(key: str) -> None:
    global _SECRET_KEY
    _SECRET_KEY = key


def set_algorithm(alg: str) -> None:
    global _ALGORITHM
    _ALGORITHM = alg


def _get_secret_key() -> str:
    if _SECRET_KEY is None:
        raise RuntimeError("JWT secret key not set. Call set_secret_key() during startup.")
    return _SECRET_KEY


def _get_algorithm() -> str:
    if _ALGORITHM is None:
        raise RuntimeError("JWT algorithm not set. Call set_algorithm() during startup.")
    return _ALGORITHM


def create_access_token(
    user_id: UUID | str,
    username: str,
    token_version: int,
    expires_delta: timedelta | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=60))
    payload = {
        "sub": str(user_id),
        "username": username,
        "jti": uuid4().hex,
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "iat": datetime.now(timezone.utc),
        "exp": expire,
        "token_version": token_version,
    }
    return jwt.encode(payload, _get_secret_key(), algorithm=_get_algorithm())


def verify_access_token_with_status(token: str) -> tuple[dict[str, Any] | None, str]:
    try:
        payload = jwt.decode(
            token,
            _get_secret_key(),
            algorithms=[_get_algorithm()],
            issuer=_ISSUER,
            audience=_AUDIENCE,
        )
        if not isinstance(payload, dict):
            return None, "invalid"
        return payload, "ok"
    except ExpiredSignatureError:
        return None, "expired"
    except JWTError:
        return None, "invalid"


def verify_access_token(token: str) -> dict[str, Any] | None:
    payload, status = verify_access_token_with_status(token)
    if status == "ok":
        return payload
    return None