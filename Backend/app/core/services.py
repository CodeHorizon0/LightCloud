from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from anyio import CapacityLimiter
from fastapi import Request

from app.core.auth_helper import JWTService
from app.core.passwords import PasswordService
from app.core.settings import Settings
from app.db.database import UserDatabase
from app.services.compression.manager import CompressionManager
from app.services.sse import EventBroker
from app.services.storage import UserStorageManager


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    settings: Settings
    database: UserDatabase
    storage: UserStorageManager
    tokens: JWTService
    passwords: PasswordService
    dummy_password_hash: str
    compression: CompressionManager
    events: EventBroker
    uploads: CapacityLimiter
    previews: CapacityLimiter
    compressed_reads: CapacityLimiter


def get_services(request: Request) -> ApplicationServices:
    return cast(ApplicationServices, request.app.state.services)
