from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from email.utils import formatdate, parsedate_to_datetime
from os import stat_result
from pathlib import Path
from typing import BinaryIO

from anyio import CapacityLimiter, WouldBlock, to_thread
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.core.request_context import Session, session_storage
from app.core.services import ApplicationServices, get_services
from app.core.settings import MIB
from app.models import FileMetadata
from app.services.archive_index import ArchiveError
from app.services.compression.manager import (
    CompressionError,
    decompress_chunks,
    next_chunk,
    read_frame,
)
from app.services.file_names import content_disposition, normalize_name
from app.services.krita import ASSETS
from app.services.preview_policy import PreviewKind, file_revision, office_mime, preview_policy
from app.services.preview_rendering import render_preview

logger = logging.getLogger(__name__)
_RANGE = re.compile(r"bytes=([0-9]{0,20})-([0-9]{0,20})", re.IGNORECASE)
PREVIEW_CSP = "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'"
MAX_PREVIEW_BYTES = 32 * MIB


def _since_matches(value: str | None, mtime: int) -> bool:
    if not value:
        return False
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.tzinfo is not None and mtime <= parsed.timestamp()
    except (ValueError, TypeError, OverflowError, OSError):
        return False


def _fresh(request: Request, etag: str, mtime: int) -> bool:
    tags = request.headers.get("if-none-match")
    if tags is not None:
        return any(tag.strip() in {"*", etag, f"W/{etag}"} for tag in tags.split(","))
    return _since_matches(request.headers.get("if-modified-since"), mtime)


def _byte_range(header: str, size: int) -> tuple[int, int]:
    match = _RANGE.fullmatch(header.strip())
    if match and size > 0:
        first, last = match.groups()
        if first:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1
            if start <= end:
                return start, end
        elif last and int(last) > 0:
            return max(0, size - int(last)), size - 1
    raise HTTPException(416, "Range not satisfiable", headers={"Content-Range": f"bytes */{size}"})


def _file_chunks(source: BinaryIO, offset: int, length: int, chunk_size: int) -> Iterator[bytes]:
    source.seek(offset)
    while length > 0:
        chunk = source.read(min(chunk_size, length))
        if not chunk:
            raise OSError("Stored file ended early")
        length -= len(chunk)
        yield chunk


def _slice_chunks(chunks: Iterator[bytes], start: int, length: int) -> Iterator[bytes]:
    for chunk in chunks:
        if start >= len(chunk):
            start -= len(chunk)
            continue
        selected = chunk[start : start + length]
        yield selected
        length -= len(selected)
        if not length:
            return
        start = 0


class BlobResponse(StreamingResponse):
    def __init__(
        self, chunks: Iterator[bytes], *, status: int, mime: str, headers: dict[str, str]
    ) -> None:
        self.resources = ExitStack()

        async def stream() -> AsyncIterator[bytes]:
            while (chunk := await to_thread.run_sync(next_chunk, chunks)) is not None:
                yield chunk

        super().__init__(stream(), status_code=status, media_type=mime, headers=headers)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        with self.resources:
            await super().__call__(scope, receive, send)


def _entity_tag(path: Path, size: int, mtime_ns: int, *, inline: bool) -> str:
    digest = hashlib.blake2b(
        f"{path.name}|{size}|{mtime_ns}|{inline}|2".encode(), digest_size=16
    ).hexdigest()
    return f'"{digest}"'


@dataclass(frozen=True, slots=True)
class FileView:
    kind: PreviewKind | None
    mime: str
    headers: dict[str, str]
    variant: str = ""
    asset: str | None = None

    @property
    def raster(self) -> bool:
        return self.kind == "image" and self.mime != "image/svg+xml"

    @property
    def generated(self) -> bool:
        return self.kind in {"archive", "krita"} or self.raster


@dataclass(frozen=True, slots=True)
class StoredFile:
    path: Path
    info: stat_result
    source: BinaryIO
    metadata: FileMetadata
    view: FileView


type CompressionFrame = tuple[str, int, bytes]


def _file_view(
    request: Request, session: Session, name: str, entry: FileMetadata, *, inline: bool
) -> FileView:
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": PREVIEW_CSP,
        "Referrer-Policy": "no-referrer",
        "Content-Disposition": content_disposition("inline" if inline else "attachment", name),
    }
    if not inline:
        return FileView(None, "application/octet-stream", headers)
    policy = preview_policy(entry, name)
    if policy is None:
        raise HTTPException(415, "Preview is not supported for this file")

    revision = file_revision(entry)
    expected = request.query_params.get("rev")
    if expected is not None and expected != revision:
        raise HTTPException(409, "File was updated")
    variant = request.query_params.get("view", "")
    asset = request.query_params.get("asset")
    if (variant or asset is not None) and (
        policy.kind != "krita"
        or variant not in {"", "details"}
        or (asset is not None and (asset not in ASSETS or variant))
    ):
        raise HTTPException(400, "Invalid preview variant")
    headers.update(
        {
            "X-Preview-Kind": policy.kind,
            "X-File-Revision": revision,
            "X-Preview-Account": str(session.user.id),
        }
    )
    return FileView(policy.kind, policy.media_type, headers, variant, asset)


async def _open_file(
    request: Request, session: Session, name: str, resources: ExitStack, *, inline: bool
) -> StoredFile:
    async with session_storage(request, session) as storage:
        entry = await storage.metadata_store.get(name)
        if entry is None:
            raise HTTPException(404, "File not found")
        path = storage.blob_path(entry["stored_path"])
        if path is None:
            raise HTTPException(404, "File not found")
        view = _file_view(request, session, name, entry, inline=inline)
        info = path.stat()
        return StoredFile(path, info, resources.enter_context(path.open("rb")), entry, view)


async def _compression_frame(
    file: StoredFile, services: ApplicationServices, resources: ExitStack
) -> CompressionFrame | None:
    if not file.metadata["stored_as_compressed"]:
        return None
    readers = services.compressed_reads
    borrower = object()
    try:
        readers.acquire_on_behalf_of_nowait(borrower)
    except WouldBlock as exc:
        raise HTTPException(
            503, "Compressed file readers are busy", headers={"Retry-After": "2"}
        ) from exc
    resources.callback(readers.release_on_behalf_of, borrower)
    size = file.metadata["original_size"]
    frame = await to_thread.run_sync(
        read_frame, file.source, max(services.settings.max_file_size, size)
    )
    if frame[1] != size:
        raise CompressionError("Stored size does not match compressed frame")
    return frame


async def _generated_preview(
    file: StoredFile, frame: CompressionFrame | None, limiter: CapacityLimiter
) -> Response | None:
    view = file.view
    size = frame[1] if frame is not None else file.info.st_size
    if view.kind is None or not view.generated or (view.raster and size > MAX_PREVIEW_BYTES):
        return None
    try:
        limiter.acquire_nowait()
    except WouldBlock as exc:
        if view.raster:
            return None
        raise HTTPException(503, "Preview workers are busy", headers={"Retry-After": "2"}) from exc
    try:
        rendered = await to_thread.run_sync(
            render_preview,
            file.source,
            frame,
            view.kind,
            file.metadata["mime"],
            view.variant,
            view.asset,
        )
    finally:
        limiter.release()
    if isinstance(rendered, dict):
        return JSONResponse(rendered, headers=view.headers)
    if rendered is not None:
        if view.asset is None:
            view.headers["X-Preview-Quality"] = "76"
        return Response(
            rendered, media_type="image/png" if view.asset else "image/jpeg", headers=view.headers
        )
    if view.kind == "krita":
        raise HTTPException(415, "Krita preview image is missing or invalid")
    await to_thread.run_sync(file.source.seek, 0)
    if frame is not None:
        await to_thread.run_sync(read_frame, file.source, size)
    return None


async def _validate_legacy_office(file: StoredFile, frame: CompressionFrame | None) -> None:
    view = file.view
    if (
        view.kind in {"document", "spreadsheet", "presentation"}
        and view.mime.startswith("application/")
        and not file.metadata.get("preview_profiled")
        and frame is None
    ):
        if await to_thread.run_sync(office_mime, file.source) != view.mime:
            raise HTTPException(415, "Invalid Office package")
        file.source.seek(0)


def _stream_response(
    request: Request, file: StoredFile, frame: CompressionFrame | None, chunk_size: int
) -> Response:
    view = file.view
    size = frame[1] if frame is not None else file.info.st_size
    mtime = int(file.info.st_mtime)
    etag = _entity_tag(file.path, size, file.info.st_mtime_ns, inline=view.kind is not None)
    headers = view.headers
    start, length, status = 0, size, 200
    if not view.generated:
        headers.update(
            {
                "ETag": etag,
                "Last-Modified": formatdate(mtime, usegmt=True),
                "Accept-Ranges": "bytes",
            }
        )
        if _fresh(request, etag, mtime):
            return Response(status_code=304, headers=headers)
        range_header = request.headers.get("range")
        if_range = request.headers.get("if-range")
        if range_header and (
            if_range is None or if_range == etag or _since_matches(if_range, mtime)
        ):
            start, end = _byte_range(range_header, size)
            length, status = end - start + 1, 206
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    headers["Content-Length"] = str(length)
    if request.method == "HEAD":
        return Response(status_code=status, media_type=view.mime, headers=headers)
    if frame is None:
        chunks = _file_chunks(file.source, start, length, chunk_size)
    else:
        chunks = decompress_chunks(file.source, frame)
        if start != 0 or length != size:
            chunks = _slice_chunks(chunks, start, length)
    return BlobResponse(chunks, status=status, mime=view.mime, headers=headers)


async def serve_file(
    request: Request, session: Session, filename: str, *, inline: bool
) -> Response:
    services = get_services(request)
    name = normalize_name(filename, services.settings.max_filename_depth)
    with ExitStack() as resources:
        file = await _open_file(request, session, name, resources, inline=inline)
        if inline and request.method == "HEAD":
            return Response(headers=file.view.headers)
        try:
            frame = await _compression_frame(file, services, resources)
            await _validate_legacy_office(file, frame)
            preview = await _generated_preview(file, frame, services.previews)
            if preview is not None:
                return preview
            response = _stream_response(
                request, file, frame, services.settings.upload_worker.chunk_size
            )
            if isinstance(response, BlobResponse):
                response.resources = resources.pop_all()
            return response
        except ArchiveError as exc:
            raise HTTPException(415, str(exc)) from exc
        except CompressionError as exc:
            logger.warning("Invalid compressed blob %s", file.path.name, exc_info=True)
            raise HTTPException(500, "Stored file is damaged") from exc
