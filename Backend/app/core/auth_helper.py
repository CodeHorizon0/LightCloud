from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import jwt


@dataclass(frozen=True, slots=True)
class AccessToken:
    user_id: UUID
    username: str
    version: int
    session_id: UUID
    expires_at: int


TokenStatus = Literal["ok", "expired", "invalid"]


class JWTService:
    def __init__(self, secret_key: str, algorithm: str) -> None:
        self.secret_key = secret_key
        self.algorithm = algorithm

    def create_access_token(
        self, user_id: UUID, username: str, version: int, expires_delta: timedelta
    ) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": str(user_id),
                "username": username,
                "token_version": version,
                "jti": uuid4().hex,
                "iat": now,
                "exp": now + expires_delta,
                "iss": "lc-backend",
                "aud": "lc-api-user",
            },
            self.secret_key,
            algorithm=self.algorithm,
        )

    def verify(self, raw_token: str) -> tuple[AccessToken | None, TokenStatus]:
        try:
            payload = jwt.decode(
                raw_token,
                self.secret_key,
                algorithms=[self.algorithm],
                issuer="lc-backend",
                audience="lc-api-user",
                options={"require": ["sub", "jti", "iss", "aud", "iat", "exp"]},
            )
            username = payload.get("username")
            version = payload.get("token_version")
            expires_at = payload["exp"]
            if (
                not isinstance(username, str)
                or type(version) is not int
                or type(expires_at) is not int
            ):
                return None, "invalid"
            return AccessToken(
                UUID(payload["sub"]), username, version, UUID(payload["jti"]), expires_at
            ), "ok"
        except jwt.ExpiredSignatureError:
            return None, "expired"
        except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError, OverflowError):
            return None, "invalid"
