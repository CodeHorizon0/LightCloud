from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from uuid import UUID, uuid4

import aiofiles
from anyio import WouldBlock, fail_after, to_thread
from fastapi import HTTPException, Request
from python_multipart.multipart import parse_options_header
from starlette.datastructures import FormData, Headers, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.request_context import Session, session_storage
from app.core.services import get_services
from app.core.settings import MIB, Settings
from app.db.sqlite import fsync_directory
from app.models import FileMetadata
from app.services.archive_index import ARCHIVE_MIMES
from app.services.compression import CompressionManager
from app.services.file_names import normalize_name
from app.services.metadata import Metadata, public_metadata
from app.services.preview_policy import classify_upload
from app.services.sse import EventBroker
from app.services.storage import UserStorage, clean_pending_blobs, commit_storage_change
from app.services.sync import MAX_REVISIONS_BYTES, check_revisions, parse_revisions

logger = logging.getLogger(__name__)
DISK_RESERVE = 128 * MIB


class UploadLimitError(MultiPartException):
    pass


class UploadParser(MultiPartParser):
    def __init__(
        self, headers: Headers, stream: AsyncGenerator[bytes, None], settings: Settings
    ) -> None:
        super().__init__(headers, stream, max_files=settings.max_upload_files, max_fields=1)
        self.max_file_size = settings.max_file_size
        self.max_batch_size = settings.max_batch_size
        self.part_size = 0
        self.batch_size = 0
        self.header_size = 0
        self.complete = False

    def on_part_begin(self) -> None:
        super().on_part_begin()
        self.part_size = self.header_size = 0

    def _add_header_bytes(self, size: int) -> None:
        self.header_size += size
        if self.header_size > 16 * 1024:
            raise UploadLimitError("Multipart headers are too large")

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._add_header_bytes(end - start)
        super().on_header_field(data, start, end)

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._add_header_bytes(end - start)
        super().on_header_value(data, start, end)

    def on_header_end(self) -> None:
        self._add_header_bytes(4)
        super().on_header_end()

    def on_headers_finished(self) -> None:
        super().on_headers_finished()
        field = self._current_part.field_name
        if field not in {"files", "revisions"} or (field == "files") != (
            self._current_part.file is not None
        ):
            raise MultiPartException("Use files and revisions fields")

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        size = end - start
        self.part_size += size
        if self._current_part.field_name == "revisions":
            if self.part_size > MAX_REVISIONS_BYTES:
                raise UploadLimitError("File revisions are too large")
            super().on_part_data(data, start, end)
            return
        self.batch_size += size
        if self.part_size > self.max_file_size or self.batch_size > self.max_batch_size:
            raise UploadLimitError("Upload size limit exceeded")
        super().on_part_data(data, start, end)

    def on_end(self) -> None:
        self.complete = True

    async def parse(self) -> FormData:
        form = await super().parse()
        if not self.complete:
            for file in self._files_to_close_on_error:
                file.close()
            raise MultiPartException("Incomplete multipart upload")
        return form


def _check_space(path: Path) -> None:
    if shutil.disk_usage(path).free < DISK_RESERVE:
        raise HTTPException(507, "Storage has insufficient free space")


async def _request_chunks(request: Request) -> AsyncGenerator[bytes, None]:
    stream = request.stream()
    temp_root = Path(tempfile.gettempdir())
    since_check = 16 * MIB
    while True:
        try:
            chunk = await asyncio.wait_for(anext(stream), timeout=30)
        except StopAsyncIteration:
            return
        except TimeoutError as exc:
            raise HTTPException(408, "Upload timed out") from exc
        if since_check >= 16 * MIB:
            await to_thread.run_sync(_check_space, temp_root)
            since_check = 0
        since_check += len(chunk)
        yield chunk


@asynccontextmanager
async def _parse_upload(request: Request, settings: Settings) -> AsyncGenerator[FormData, None]:
    media_type, params = parse_options_header(request.headers.get("content-type", ""))
    if media_type.lower() != b"multipart/form-data":
        raise HTTPException(415, "Expected multipart/form-data")
    boundary = params.get(b"boundary", b"")
    if not 1 <= len(boundary) <= 70 or not boundary.isascii() or not boundary.strip():
        raise HTTPException(400, "Invalid multipart boundary")
    try:
        with fail_after(30 * 60):
            form = await UploadParser(request.headers, _request_chunks(request), settings).parse()
    except TimeoutError as exc:
        raise HTTPException(408, "Upload timed out") from exc
    except UploadLimitError as exc:
        raise HTTPException(413, exc.message) from exc
    except MultiPartException as exc:
        raise HTTPException(400, exc.message) from exc
    try:
        yield form
    finally:
        await form.close()


async def _copy_upload(upload: UploadFile, path: Path, settings: Settings) -> int:
    size = 0
    since_check = 16 * MIB
    async with aiofiles.open(path, "xb") as destination:
        while chunk := await upload.read(settings.upload_worker.chunk_size):
            if since_check >= 16 * MIB:
                await to_thread.run_sync(_check_space, path.parent)
                since_check = 0
            await destination.write(chunk)
            size += len(chunk)
            since_check += len(chunk)
        await destination.flush()
        await to_thread.run_sync(os.fsync, destination.fileno())
    return size


async def _stage_file(
    upload: UploadFile,
    filename: str,
    staging: Path,
    settings: Settings,
    compressor: CompressionManager,
    status: UploadStatus,
) -> FileMetadata:
    path = staging / uuid4().hex
    status.emit("queued", "File queued for upload", filename)
    status.emit("uploading", "Receiving file", filename)
    size = await _copy_upload(upload, path, settings)
    await upload.close()
    status.emit("uploaded", "File received", filename, size)
    status.emit("analyzing", "Analyzing compression profile", filename, size)
    analysis = await compressor.analyze_path(path, filename_hint=filename)
    profile, scan = analysis
    mime = await to_thread.run_sync(classify_upload, path, profile.mime)
    algorithm = "copy"
    stored_size = size
    if (
        scan.should_compress
        and profile.mime not in ARCHIVE_MIMES
        and size <= settings.compression.max_source_size
    ):
        status.emit("compressing", f"Compressing with {scan.recommended_algorithm}", filename, size)
        compressed = path.with_suffix(".cmp")
        await to_thread.run_sync(_check_space, staging)
        result = await compressor.compress_path(
            path,
            compressed,
            level=settings.compression_level,
            analysis=analysis,
        )
        compressed_size = compressed.stat().st_size
        if compressed_size < size:
            path.unlink()
            path = compressed
            stored_size = compressed_size
            algorithm = result.algorithm
        else:
            compressed.unlink()
    status.emit("finalizing", "Writing metadata", filename, stored_size)
    return {
        "stored_path": path.name,
        "stored_as_compressed": algorithm != "copy",
        "compression_algorithm": algorithm,
        "original_size": size,
        "stored_size": stored_size,
        "compression_percent": round(100 * (1 - stored_size / size), 2) if size else 0.0,
        "mime": mime,
        "preview_profiled": True,
        "category": profile.category,
    }


class UploadStatus:
    def __init__(self, broker: EventBroker, user_id: UUID, count: int) -> None:
        self.broker = broker
        self.user_id = user_id
        self.count = count
        self.batch_id = uuid4().hex
        self.index = 0

    def emit(self, stage: str, message: str, filename: str | None = None, size: int = 0) -> None:
        data: dict[str, object] = {
            "batch_id": self.batch_id,
            "stage": stage,
            "total_files": self.count,
            "message": message,
        }
        if filename is not None:
            data.update(filename=filename, index=self.index, bytes_processed=size)
        if stage == "batch_done":
            data["stored_files"] = self.count
        self.broker.upload_status(self.user_id, data)


async def _commit_batch(
    request: Request,
    session: Session,
    settings: Settings,
    staging: Path,
    staged: dict[str, FileMetadata],
    revisions: dict[str, str | None] | None,
) -> None:
    async with session_storage(request, session, create=True) as storage:
        previous = await storage.metadata_store.load(list(staged))
        if revisions is not None:
            check_revisions(previous, list(staged), revisions)
        await storage.metadata_store.check_quota(
            staged, settings.user_file_limit, settings.user_quota_mb * MIB
        )
        await commit_storage_change(
            get_services(request).events,
            session.user.id,
            partial(_publish_files, storage, staging, staged),
        )
        await clean_pending_blobs(storage)


async def _publish_files(storage: UserStorage, staging: Path, staged: Metadata) -> None:
    await storage.metadata_store.stage_blobs([entry["stored_path"] for entry in staged.values()])
    await to_thread.run_sync(_move_files, storage, staging, staged)
    await storage.metadata_store.commit(staged)


def _move_files(storage: UserStorage, staging: Path, staged: Metadata) -> None:
    for entry in staged.values():
        leaf = entry["stored_path"]
        os.replace(staging / leaf, storage.root_dir / leaf)
    fsync_directory(storage.root_dir)


def _upload_parts(form: FormData, max_depth: int) -> dict[str, UploadFile]:
    files: dict[str, UploadFile] = {}
    for field, upload in form.multi_items():
        if field == "revisions":
            continue
        if not isinstance(upload, UploadFile):
            raise HTTPException(400, "Expected files")
        filename = normalize_name(upload.filename or "file", max_depth)
        if filename in files:
            raise HTTPException(400, "Duplicate filename in upload")
        files[filename] = upload
    if not files:
        raise HTTPException(400, "No files provided")
    return files


async def store_upload(
    request: Request, session: Session, *, require_revisions: bool = False
) -> list[dict[str, object]]:
    services = get_services(request)
    settings = services.settings
    compressor = services.compression
    broker = services.events
    limiter = services.uploads
    try:
        limiter.acquire_nowait()
    except WouldBlock as exc:
        raise HTTPException(
            429, "Too many uploads in progress", headers={"Retry-After": "5"}
        ) from exc

    try:
        async with _parse_upload(request, settings) as form:
            files = _upload_parts(form, settings.max_filename_depth)
            values = form.getlist("revisions")
            if require_revisions and not values:
                raise HTTPException(428, "File revisions are required")
            revisions = parse_revisions(values[0]) if values else None
            if revisions is not None and set(revisions) != files.keys():
                raise HTTPException(400, "A base revision is required for every file")
            if revisions is not None:
                async with session_storage(request, session) as storage:
                    check_revisions(
                        await storage.metadata_store.load(list(files)), list(files), revisions
                    )
            status = UploadStatus(broker, session.user.id, len(files))
            staging_root = services.storage.root / ".staging"
            staging_root.mkdir(mode=0o700, exist_ok=True)
            status.emit("batch_started", "Upload started")
            try:
                with tempfile.TemporaryDirectory(dir=staging_root) as directory:
                    staging = Path(directory)
                    staged: dict[str, FileMetadata] = {}
                    for status.index, (name, upload) in enumerate(files.items(), start=1):
                        staged[name] = await _stage_file(
                            upload, name, staging, settings, compressor, status
                        )
                    await _commit_batch(request, session, settings, staging, staged, revisions)
            except HTTPException as exc:
                status.emit("error", str(exc.detail))
                raise
            except OSError as exc:
                status.emit("error", "Upload failed")
                logger.exception("Upload could not be saved")
                raise HTTPException(500, "Upload could not be saved") from exc
            for status.index, (name, entry) in enumerate(staged.items(), start=1):
                status.emit("done", "File stored successfully", name, entry["stored_size"])
            status.emit("batch_done", "Upload complete")
            return [
                {"filename": name, "message": "File uploaded", **entry}
                for name, entry in public_metadata(staged).items()
            ]
    finally:
        limiter.release()
