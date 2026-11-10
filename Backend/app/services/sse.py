from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException

HEARTBEAT_INTERVAL = 15


@dataclass(frozen=True, slots=True)
class Event:
    name: str
    data: str = ""
    id: str | None = None

    def render(self) -> str:
        lines = self.data.split("\n")
        identifier = f"id: {self.id}\n" if self.id is not None else ""
        return (
            identifier
            + f"event: {self.name}\n"
            + "".join(f"data: {line}\n" for line in lines)
            + "\n"
        )


METADATA_CHANGED = Event("metadata_update")
AUTH_CHANGED = Event("auth_changed")


class EventBroker:
    def __init__(self) -> None:
        self.clients: dict[UUID, set[asyncio.Queue[Event]]] = {}
        self.client_count = 0

    @asynccontextmanager
    async def subscribe(self, user_id: UUID) -> AsyncIterator[asyncio.Queue[Event]]:
        clients = self.clients.get(user_id)
        if self.client_count >= 256 or (clients is not None and len(clients) >= 8):
            raise HTTPException(429, "Too many event streams")
        if clients is None:
            clients = self.clients.setdefault(user_id, set())
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=32)
        clients.add(queue)
        self.client_count += 1
        try:
            yield queue
        finally:
            clients.remove(queue)
            self.client_count -= 1
            if not clients:
                del self.clients[user_id]

    def publish(self, user_id: UUID, event: Event) -> None:
        for queue in self.clients.get(user_id, ()):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    def upload_status(self, user_id: UUID, data: dict[str, object]) -> None:
        if user_id in self.clients:
            self.publish(user_id, Event("upload_status", json.dumps(data, ensure_ascii=True)))
