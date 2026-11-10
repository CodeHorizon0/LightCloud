from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api.routes.metadata import subscribe
from app.core.request_context import Authenticated, Session, current_session_user, session_storage
from app.services.metadata import MetadataSnapshot
from app.services.sse import AUTH_CHANGED, METADATA_CHANGED, Event
from app.services.storage import UserStorage
from app.services.sync import SYNC_INTERVAL, SyncSnapshot

router = APIRouter(tags=["sync"])


async def read_state(
    request: Request,
    session: Session,
    storage: UserStorage,
    previous: MetadataSnapshot | None,
    state: SyncSnapshot | None,
) -> tuple[MetadataSnapshot, SyncSnapshot] | None:
    async with storage.lock():
        user = await current_session_user(request, session)
        if user is None:
            return None
        snapshot = await storage.metadata_store.snapshot(previous)
        if state is None or snapshot is not previous:
            state = SyncSnapshot.from_metadata(user.id, snapshot)
        return snapshot, state


@router.get("/sync")
async def sync_snapshot(request: Request, session: Authenticated) -> Response:
    async with session_storage(request, session) as storage:
        user = await current_session_user(request, session)
        if user is None:
            raise HTTPException(401, "Invalid session")
        state = SyncSnapshot.from_metadata(user.id, await storage.metadata_store.snapshot(None))
    etag = f'"{state.cursor}"'
    headers = {"Cache-Control": "no-store", "ETag": etag, "X-Sync-Account": state.account}
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(candidate.strip().removeprefix("W/") in {etag, "*"} for candidate in candidates):
        return Response(status_code=304, headers=headers)
    return JSONResponse(state.payload(), headers=headers)


def ready_event(state: SyncSnapshot) -> Event:
    return Event(
        "sync_ready",
        json.dumps({"protocol": 1, "account": state.account, "cursor": state.cursor}),
        state.cursor,
    )


@router.get("/sync/stream")
async def sync_stream(
    request: Request,
    session: Authenticated,
    queue: Annotated[asyncio.Queue[Event], Depends(subscribe)],
    cursor: Annotated[str | None, Query(max_length=64, pattern=r"^[0-9a-f]{64}$")] = None,
) -> StreamingResponse:
    async with session_storage(request, session) as storage:
        initial_snapshot = await storage.metadata_store.snapshot(None)
    resume = cursor or request.headers.get("last-event-id")

    async def events() -> AsyncIterator[str]:
        previous: MetadataSnapshot | None = initial_snapshot
        state: SyncSnapshot | None = None
        event: Event | None = METADATA_CHANGED
        while True:
            result = await read_state(request, session, storage, previous, state)
            if result is None:
                break
            snapshot, incoming = result
            if state is None and incoming.cursor != resume:
                yield Event(
                    "sync_snapshot", json.dumps(incoming.payload()), incoming.cursor
                ).render()
            elif state is not None and incoming.cursor != state.cursor:
                yield Event(
                    "sync_patch", json.dumps(incoming.patch(state)), incoming.cursor
                ).render()
            elif event is None or event in {METADATA_CHANGED, AUTH_CHANGED}:
                yield ready_event(incoming).render()
            if event is not None and event.name == "upload_status":
                yield event.render()
            previous, state = snapshot, incoming
            try:
                event = await asyncio.wait_for(queue.get(), timeout=SYNC_INTERVAL)
            except TimeoutError:
                event = None
        yield Event("close_connection").render()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
