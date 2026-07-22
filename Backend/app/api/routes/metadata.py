from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import Response
from fastapi.responses import StreamingResponse

from app.core.request_context import get_authenticated_username
from app.services.sse import add_client, remove_client
from app.services.storage import UserStorageManager

router = APIRouter()


def _format_sse(
    *,
    event: str | None = None,
    data: str | None = None,
    event_id: int | None = None,
    retry: int | None = None,
) -> str:
    lines: list[str] = []

    if event_id is not None:
        lines.append(f"id: {event_id}")
    if event is not None:
        lines.append(f"event: {event}")
    if retry is not None:
        lines.append(f"retry: {retry}")
    if data is not None:
        for line in data.splitlines() or [""]:
            lines.append(f"data: {line}")

    return "\n".join(lines) + "\n\n"


@router.get("/metadata/stream")
async def metadata_stream(request: Request):

    app = request.app
    username = get_authenticated_username(request)
    if not username:
        return Response(status_code=401)
    
    storage_manager: UserStorageManager = app.state.storage_manager
    storage = await storage_manager.ensure_user_storage(username)
    client_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue(maxsize=256)

    await add_client(app, username, client_queue)

    async def event_generator() -> AsyncIterator[str]:
        last_meta: object = object()
        event_id = 0
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    queued = await asyncio.wait_for(client_queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    queued = None
                if queued is not None:
                    yield _format_sse(
                        event=queued["event"],
                        data=queued["data"],
                        retry=1000,
                    )
                    continue
                meta = await storage.metadata_store.load()
                if meta != last_meta:
                    event_id += 1
                    yield _format_sse(
                        event="metadata_update",
                        data=json.dumps(meta, ensure_ascii=False),
                        event_id=event_id,
                        retry=1000,
                    )
                    last_meta = meta
        except asyncio.CancelledError:
            pass
        finally:
            await remove_client(app, username, client_queue)
            
    headers = {"Cache-Control": "no-cache","Connection": "keep-alive","X-Accel-Buffering": "no"}

    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream", 
        headers=headers
    )
