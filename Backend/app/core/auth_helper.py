# app/core/auth_helper.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from jose import ExpiredSignatureError, JWTError, jwt


class JWTService:
    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        issuer: str = "lc-backend",
        audience: str = "lc-api-user",
    ):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.issuer = issuer
        self.audience = audience

    def create_access_token(
        self,
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
            "iss": self.issuer,
            "aud": self.audience,
            "iat": datetime.now(timezone.utc),
            "exp": expire,
            "token_version": token_version,
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def verify_token_with_status(self, token: str) -> tuple[dict[str, Any] | None, str]:
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                issuer=self.issuer,
                audience=self.audience,
            )
            if not isinstance(payload, dict):
                return None, "invalid"
            return payload, "ok"
        except ExpiredSignatureError:
            return None, "expired"
        except JWTError:
            return None, "invalid"

    def verify_token(self, token: str) -> dict[str, Any] | None:
        payload, status = self.verify_token_with_status(token)
        if status == "ok":
            return payload
        return None