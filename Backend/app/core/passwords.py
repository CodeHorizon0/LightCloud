from __future__ import annotations

from collections import OrderedDict, deque
from time import monotonic

import bcrypt
from anyio import CapacityLimiter, WouldBlock, to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError
from fastapi import HTTPException

_hasher = PasswordHasher()
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def _verify(password: str, password_hash: str) -> bool:
    try:
        if password_hash.startswith(_BCRYPT_PREFIXES):
            return bcrypt.checkpw(password.encode()[:72], password_hash.encode())
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHash, ValueError):
        return False


class PasswordService:
    def __init__(self) -> None:
        self.workers = CapacityLimiter(2)
        self.attempts: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self.global_attempts: deque[float] = deque()

    def check_rate(self, action: str, ip: str) -> None:
        now = monotonic()
        key = (action, ip)
        recent = self.attempts.setdefault(key, deque())
        self.attempts.move_to_end(key)
        if len(self.attempts) > 4096:
            self.attempts.popitem(last=False)
        for history in (recent, self.global_attempts):
            while history and history[0] <= now - 60:
                history.popleft()
        if len(recent) >= (5 if action == "register" else 20) or len(self.global_attempts) >= 180:
            raise HTTPException(
                429, "Too many authentication attempts", headers={"Retry-After": "60"}
            )
        recent.append(now)
        self.global_attempts.append(now)

    async def hash(self, password: str) -> str:
        try:
            self.workers.acquire_nowait()
        except WouldBlock as exc:
            raise HTTPException(503, "Authentication is busy") from exc
        try:
            return await to_thread.run_sync(_hasher.hash, password)
        finally:
            self.workers.release()

    async def verify(self, password: str, password_hash: str) -> bool:
        try:
            self.workers.acquire_nowait()
        except WouldBlock as exc:
            raise HTTPException(503, "Authentication is busy") from exc
        try:
            return await to_thread.run_sync(_verify, password, password_hash)
        finally:
            self.workers.release()
