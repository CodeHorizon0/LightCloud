from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI


def _get_registry(app: FastAPI) -> dict[str, set[asyncio.Queue[dict[str, str]]]]:
    registry = getattr(app.state, "sse_clients", None)
    if registry is None:
        registry = {}
        app.state.sse_clients = registry
    return registry


def _get_lock(app: FastAPI) -> asyncio.Lock:
    lock = getattr(app.state, "sse_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        app.state.sse_lock = lock
    return lock


async def add_client(app: FastAPI, username: str, queue: asyncio.Queue[dict[str, str]]) -> None:
    registry = _get_registry(app)
    lock = _get_lock(app)

    async with lock:
        clients = registry.setdefault(username, set())
        clients.add(queue)


async def remove_client(app: FastAPI, username: str, queue: asyncio.Queue[dict[str, str]]) -> None:
    registry = _get_registry(app)
    lock = _get_lock(app)

    async with lock:
        clients = registry.get(username)
        if clients is None:
            return
        clients.discard(queue)
        if not clients:
            registry.pop(username, None)


async def broadcast_event(app: FastAPI, username: str, event: str, data: Any) -> None:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    registry = _get_registry(app)
    lock = _get_lock(app)

    async with lock:
        queues = list(registry.get(username, set()))

    for queue in queues:
        try:
            queue.put_nowait({"event": event, "data": payload})
        except asyncio.QueueFull:
            continue
