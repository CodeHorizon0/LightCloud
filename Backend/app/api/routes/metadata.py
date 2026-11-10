from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.request_context import Authenticated, session_is_active, session_storage
from app.core.services import get_services
from app.services.metadata import MetadataSnapshot
from app.services.sse import AUTH_CHANGED, HEARTBEAT_INTERVAL, METADATA_CHANGED, Event

router = APIRouter()


async def subscribe(
    request: Request, session: Authenticated
) -> AsyncIterator[asyncio.Queue[Event]]:
    async with get_services(request).events.subscribe(session.user.id) as queue:
        yield queue


@router.get("/metadata/stream")
async def metadata_stream(
    request: Request,
    session: Authenticated,
    queue: Annotated[asyncio.Queue[Event], Depends(subscribe)],
) -> StreamingResponse:
    async with session_storage(request, session) as storage:
        store = storage.metadata_store

    async def events() -> AsyncIterator[str]:
        previous: MetadataSnapshot | None = None
        event: Event | None = METADATA_CHANGED
        while await session_is_active(request, session):
            if event is None or event == METADATA_CHANGED:
                snapshot = await store.snapshot(previous)
                changed = previous is None or (
                    snapshot is not previous and snapshot.data != previous.data
                )
                previous = snapshot
                if changed:
                    yield Event("metadata_update", snapshot.data).render()
                elif event is None:
                    yield ": keep-alive\n\n"
            elif event != AUTH_CHANGED:
                yield event.render()
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL)
            except TimeoutError:
                event = None
        yield Event("close_connection").render()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
