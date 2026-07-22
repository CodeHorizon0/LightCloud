# app/core/auth_helper.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import ExpiredSignatureError, JWTError, jwt

_SECRET_KEY: str | None = None
_ALGORITHM: str | None = None        

def set_secret_key(key: str) -> None:
    """Устанавливает секретный ключ для JWT (вызывается при старте приложения)."""
    global _SECRET_KEY
    _SECRET_KEY = key


def set_algorithm(alg: str) -> None:
    """Устанавливает алгоритм подписи JWT (вызывается при старте приложения)."""
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


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=60))
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _get_secret_key(), algorithm=_get_algorithm())


def verify_access_token_with_status(token: str) -> tuple[dict[str, Any] | None, str]:
    """Возвращает payload токена и статус проверки.

    Статус:
    - ok: токен валиден
    - expired: токен истек
    - invalid: токен поврежден, подписан неверно или невалиден
    """
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[_get_algorithm()])
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