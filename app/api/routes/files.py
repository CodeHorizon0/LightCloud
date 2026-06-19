from __future__ import annotations

import asyncio
import contextlib
import hashlib
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
import os
import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import AsyncIterator, Awaitable, Callable
from urllib.parse import quote

import aiofiles
from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.request_context import get_authenticated_username
from app.core.settings import Settings
from app.models import DeleteFilesRequest
from app.services.sse import broadcast_event
from app.services.storage import UserStorage, UserStorageManager

router = APIRouter()

_PREVIEWABLE_MIME_EXACT = {
    "application/json",
    "application/pdf",
    "application/xml",
    "application/xhtml+xml",
    "application/javascript",
    "application/typescript",
    "application/sql",
    "application/toml",
    "image/svg+xml",
    "text/markdown",
    "text/csv",
    "text/tab-separated-values",
}

_PREVIEWABLE_MIME_PREFIXES = ("text/", "image/", "audio/", "video/")


def _safe_remove(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError, PermissionError):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def _safe_remove_many(*paths: Path) -> None:
    for path in paths:
        _safe_remove(path)


def _normalize_uploaded_name(raw_name: str, max_depth: int) -> str:
    name = (raw_name or "file").replace("\\", "/").strip()

    if not name:
        return "file"

    p = PurePosixPath(name)

    if p.is_absolute():
        raise HTTPException(status_code=400, detail="Invalid filename")

    parts: list[str] = []
    for part in p.parts:
        if part in {".", ""}:
            continue
        if part == "..":
            raise HTTPException(status_code=400, detail="Invalid filename")
        parts.append(part)

    if not parts:
        return "file"

    if len(parts) > max_depth:
        raise HTTPException(status_code=400, detail="Filename nested too deep")

    return "/".join(parts)


def _build_storage_paths(storage: UserStorage, logical_name: str) -> tuple[Path, Path, Path]:
    unique_id = uuid.uuid4().hex
    safe_leaf = Path(logical_name).name or "file"

    tmp_path = storage.root_dir / f"tmp_{unique_id}_{safe_leaf}"
    compressed_path = storage.root_dir / f"{unique_id}_{safe_leaf}.cmp"
    final_path = storage.root_dir / f"{unique_id}_{safe_leaf}"

    return tmp_path, compressed_path, final_path


def _ensure_inside_storage(storage: UserStorage, path: Path) -> None:
    storage_root = storage.root_dir.resolve()
    resolved = path.resolve(strict=False)

    if resolved != storage_root and storage_root not in resolved.parents:
        raise HTTPException(status_code=400, detail="Invalid stored path")


def _get_username(request: Request) -> str:
    username = get_authenticated_username(request)
    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return username


def _storage_manager(request: Request) -> UserStorageManager:
    manager = getattr(request.app.state, "storage_manager", None)
    if manager is None:
        raise HTTPException(status_code=500, detail="Storage manager is not initialized")
    return manager


def _compression_manager(request: Request):
    manager = getattr(request.app.state, "compression_manager", None)
    if manager is None:
        raise HTTPException(status_code=500, detail="Compression manager is not initialized")
    return manager


def _settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(status_code=500, detail="Settings are not initialized")
    return settings


async def _emit_upload_status(
    request: Request,
    username: str,
    batch_id: str,
    *,
    stage: str,
    filename: str,
    index: int,
    total_files: int,
    bytes_processed: int | None = None,
    message: str | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "batch_id": batch_id,
        "stage": stage,
        "filename": filename,
        "index": index,
        "total_files": total_files,
    }
    if bytes_processed is not None:
        payload["bytes_processed"] = bytes_processed
    if message is not None:
        payload["message"] = message
    if extra:
        payload.update(extra)
    await broadcast_event(request.app, username, "upload_status", payload)


def _adaptive_chunk_size(size: int, base_chunk_size: int) -> int:
    base = max(2 * 1024 * 1024, int(base_chunk_size))
    current = max(0, int(size))

    if current <= 16 * 1024 * 1024:
        target = 2 * 1024 * 1024
    elif current <= 128 * 1024 * 1024:
        target = 4 * 1024 * 1024
    elif current <= 1024 * 1024 * 1024:
        target = 8 * 1024 * 1024
    else:
        target = 16 * 1024 * 1024

    return min(max(base, target), 16 * 1024 * 1024)


def _ascii_fallback_filename(filename: str) -> str:
    safe = filename.encode("ascii", "ignore").decode("ascii").strip()
    safe = safe.replace('"', "'").replace("\\", "_").replace("/", "_")
    return safe or "file"


def _content_disposition(disposition: str, filename: str) -> str:
    base_name = Path(filename).name or "file"
    fallback = _ascii_fallback_filename(base_name)
    encoded = quote(base_name, safe="")
    return f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def _http_datetime(st_mtime: float) -> str:
    dt = datetime.fromtimestamp(st_mtime, tz=timezone.utc)
    return format_datetime(dt, usegmt=True)


def _build_etag(
    *,
    stored_path: Path,
    logical_name: str,
    stored_as_compressed: bool,
    compression_algorithm: str,
    original_size: int,
    stored_size: int,
    category: str,
    mime: str,
) -> str:
    stat = stored_path.stat()
    seed = "|".join(
        [
            stored_path.as_posix(),
            str(stat.st_mtime_ns),
            str(stat.st_size),
            logical_name,
            "1" if stored_as_compressed else "0",
            compression_algorithm,
            str(original_size),
            str(stored_size),
            category,
            mime,
        ]
    )
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=16).hexdigest()
    return f'"{digest}"'


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False

    for token in if_none_match.split(","):
        candidate = token.strip()
        if not candidate:
            continue
        if candidate == "*" or candidate == etag or candidate == f"W/{etag}":
            return True
    return False


def _ims_matches(if_modified_since: str | None, last_modified: str) -> bool:
    if not if_modified_since:
        return False

    try:
        request_dt = parsedate_to_datetime(if_modified_since)
        last_dt = parsedate_to_datetime(last_modified)
    except (TypeError, ValueError, IndexError, OverflowError):
        return False

    if request_dt is None or last_dt is None:
        return False

    if request_dt.tzinfo is None:
        request_dt = request_dt.replace(tzinfo=timezone.utc)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)

    return last_dt <= request_dt


def _cache_is_fresh(request: Request, etag: str, last_modified: str) -> bool:
    return _etag_matches(request.headers.get("if-none-match"), etag) or _ims_matches(
        request.headers.get("if-modified-since"),
        last_modified,
    )


def _is_previewable_mime(mime: str) -> bool:
    lowered = (mime or "").strip().lower()
    if not lowered:
        return False
    if lowered.startswith(_PREVIEWABLE_MIME_PREFIXES):
        return True
    return lowered in _PREVIEWABLE_MIME_EXACT


async def _save_upload(
    upload: UploadFile,
    destination: Path,
    base_chunk_size: int,
    max_file_size: int,
    *,
    progress_callback: Callable[[int, bool], Awaitable[None]] | None = None,
    progress_emit_every: int | None = None,
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    chunk_size = _adaptive_chunk_size(total, base_chunk_size)
    emit_every = max(1024 * 1024, int(progress_emit_every or (chunk_size * 8)))
    next_emit = emit_every

    if progress_callback is not None:
        await progress_callback(0, False)

    async with aiofiles.open(destination, "wb") as out:
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break

            total += len(chunk)
            if total > max_file_size:
                raise HTTPException(
                    status_code=413,
                    detail=f"File {upload.filename} exceeds maximum size {max_file_size // (1024 * 1024)}MB",
                )

            await out.write(chunk)
            chunk_size = _adaptive_chunk_size(total, base_chunk_size)

            if progress_callback is not None and total >= next_emit:
                await progress_callback(total, False)
                next_emit = total + emit_every

    if progress_callback is not None:
        await progress_callback(total, True)

    return total


async def _stream_file(path: Path, chunk_size: int) -> AsyncIterator[bytes]:
    async with aiofiles.open(path, "rb") as fh:
        while True:
            chunk = await fh.read(chunk_size)
            if not chunk:
                break
            yield chunk


async def _guarded_stream(request: Request, iterator: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    async for chunk in iterator:
        if await request.is_disconnected():
            break
        yield chunk


async def _serve_stored_file(request: Request, filename: str, *, inline: bool) -> Response:
    settings = _settings(request)
    storage_manager = _storage_manager(request)
    compression_manager = _compression_manager(request)
    username = _get_username(request)

    logical_name = _normalize_uploaded_name(filename, settings.max_filename_depth)
    storage = await storage_manager.get_existing_storage(username)
    if storage is None:
        return Response(status_code=404)

    async with storage.file_lock:
        if storage.deleted or not storage.root_dir.exists():
            return Response(status_code=404)

        meta = await storage.metadata_store.load()
        file_meta = meta.get(logical_name)
        if file_meta is None:
            return Response(status_code=404)

        stored_path_value = file_meta.get("stored_path")
        if not isinstance(stored_path_value, str) or not stored_path_value:
            return Response(status_code=404)

        stored_path = Path(stored_path_value)
        if not stored_path.exists():
            return Response(status_code=404)

        _ensure_inside_storage(storage, stored_path)

        mime = str(file_meta.get("mime") or "application/octet-stream")
        category = str(file_meta.get("category") or "binary")
        compression_algorithm = str(file_meta.get("compression_algorithm") or "copy")
        stored_as_compressed = bool(file_meta.get("stored_as_compressed"))
        original_size = int(file_meta.get("original_size") or 0)
        stored_size = int(file_meta.get("stored_size") or stored_path.stat().st_size)
        stat = stored_path.stat()

    if inline and not _is_previewable_mime(mime):
        raise HTTPException(status_code=415, detail="Preview is not supported for this file type")

    last_modified = _http_datetime(stat.st_mtime)
    etag = _build_etag(
        stored_path=stored_path,
        logical_name=logical_name,
        stored_as_compressed=stored_as_compressed,
        compression_algorithm=compression_algorithm,
        original_size=original_size,
        stored_size=stored_size,
        category=category,
        mime=mime,
    )

    cache_headers = {
        "Cache-Control": f"public, max-age={settings.cache_duration}",
        "ETag": etag,
        "Last-Modified": last_modified,
        "X-Content-Type-Options": "nosniff",
    }

    if _cache_is_fresh(request, etag, last_modified):
        return Response(status_code=304, headers=cache_headers)

    media_type = mime if inline else "application/octet-stream"

    headers = dict(cache_headers)
    headers["Content-Disposition"] = _content_disposition("inline" if inline else "attachment", logical_name)

    async def body_iterator() -> AsyncIterator[bytes]:
        async with storage.file_lock:
            if storage.deleted or not storage.root_dir.exists():
                return

            if not stored_path.exists():
                return

            if stored_as_compressed:
                stream = await compression_manager.stream_decompressed_path(
                    stored_path,
                    max_size=settings.max_file_size,
                )
                async for chunk in stream:
                    if await request.is_disconnected():
                        break
                    yield chunk
            else:
                chunk_size = _adaptive_chunk_size(stored_size, settings.chunk_size)
                async for chunk in _stream_file(stored_path, chunk_size):
                    if await request.is_disconnected():
                        break
                    yield chunk

    return StreamingResponse(
        body_iterator(),
        media_type=media_type,
        headers=headers,
    )


@router.post("/upload")
async def upload_files(request: Request, files: list[UploadFile] = File(...)) -> JSONResponse:
    settings = _settings(request)
    storage_manager = _storage_manager(request)
    compression_manager = _compression_manager(request)
    username = _get_username(request)
    storage = await storage_manager.ensure_user_storage(username)

    if len(files) > settings.max_upload_files:
        raise HTTPException(status_code=400, detail=f"Too many files. Maximum {settings.max_upload_files}.")

    batch_id = uuid.uuid4().hex
    total_files = len(files)
    results: list[dict[str, object]] = []

    await broadcast_event(
        request.app,
        username,
        "upload_status",
        {
            "batch_id": batch_id,
            "stage": "batch_started",
            "total_files": total_files,
        },
    )

    async with storage.file_lock:
        for index, upload in enumerate(files, start=1):
            logical_name = _normalize_uploaded_name(upload.filename or "file", settings.max_filename_depth)
            tmp_path, compressed_path, final_path = _build_storage_paths(storage, logical_name)
            progress_step = max(8 * 1024 * 1024, _adaptive_chunk_size(0, settings.chunk_size) * 8)

            async def progress_callback(bytes_processed: int, finished: bool) -> None:
                stage = "uploading" if not finished else "uploaded"
                await _emit_upload_status(
                    request,
                    username,
                    batch_id,
                    stage=stage,
                    filename=logical_name,
                    index=index,
                    total_files=total_files,
                    bytes_processed=bytes_processed,
                    message="Receiving file" if not finished else "File received",
                    extra={"total_bytes": bytes_processed if finished else None},
                )

            try:
                await _emit_upload_status(
                    request,
                    username,
                    batch_id,
                    stage="queued",
                    filename=logical_name,
                    index=index,
                    total_files=total_files,
                    message="File queued for upload",
                )

                original_size = await _save_upload(
                    upload,
                    tmp_path,
                    settings.chunk_size,
                    settings.max_file_size,
                    progress_callback=progress_callback,
                    progress_emit_every=progress_step,
                )

                await _emit_upload_status(
                    request,
                    username,
                    batch_id,
                    stage="analyzing",
                    filename=logical_name,
                    index=index,
                    total_files=total_files,
                    bytes_processed=original_size,
                    message="Analyzing compression profile",
                )
                scan = await compression_manager.analyze_path(tmp_path, filename_hint=upload.filename)

                if scan.should_compress:
                    await _emit_upload_status(
                        request,
                        username,
                        batch_id,
                        stage="compressing",
                        filename=logical_name,
                        index=index,
                        total_files=total_files,
                        bytes_processed=original_size,
                        message=f"Compressing with {scan.recommended_algorithm}",
                    )
                    result = await compression_manager.compress_path(
                        tmp_path,
                        compressed_path,
                        force=True,
                        algorithm=scan.recommended_algorithm,
                        filename_hint=upload.filename,
                    )
                    stored_path = Path(result.output_path)
                    stored_size = stored_path.stat().st_size
                    stored_as_compressed = stored_size < original_size
                    compression_algorithm = result.algorithm if stored_as_compressed else "copy"

                    if stored_as_compressed:
                        _safe_remove(tmp_path)
                    else:
                        await asyncio.to_thread(os.replace, tmp_path, final_path)
                        _safe_remove(compressed_path)
                        stored_path = final_path
                        stored_size = original_size
                else:
                    await asyncio.to_thread(os.replace, tmp_path, final_path)
                    stored_path = final_path
                    stored_as_compressed = False
                    stored_size = original_size
                    compression_algorithm = "copy"

                await _emit_upload_status(
                    request,
                    username,
                    batch_id,
                    stage="finalizing",
                    filename=logical_name,
                    index=index,
                    total_files=total_files,
                    bytes_processed=stored_size,
                    message="Writing metadata",
                )

                compression_percent = 0.0
                if stored_as_compressed and original_size > 0:
                    compression_percent = round(100 - (stored_size / original_size * 100), 2)

                previous_entry = await storage.metadata_store.upsert(
                    logical_name,
                    {
                        "stored_path": stored_path.as_posix(),
                        "stored_as_compressed": stored_as_compressed,
                        "compression_algorithm": compression_algorithm,
                        "original_size": original_size,
                        "stored_size": stored_size,
                        "compression_percent": compression_percent,
                        "mime": scan.mime,
                        "category": scan.category,
                    },
                )

                if isinstance(previous_entry, dict):
                    previous_path_str = previous_entry.get("stored_path")
                    if isinstance(previous_path_str, str) and previous_path_str:
                        previous_path = Path(previous_path_str)
                        if previous_path.as_posix() != stored_path.as_posix():
                            _safe_remove(previous_path)

                results.append(
                    {
                        "filename": logical_name,
                        "message": "File uploaded",
                        "stored_as_compressed": stored_as_compressed,
                        "compression_algorithm": compression_algorithm,
                        "stored_path": stored_path.as_posix(),
                        "original_size": original_size,
                        "stored_size": stored_size,
                        "compression_percent": compression_percent,
                    }
                )

                await _emit_upload_status(
                    request,
                    username,
                    batch_id,
                    stage="done",
                    filename=logical_name,
                    index=index,
                    total_files=total_files,
                    bytes_processed=stored_size,
                    message="File stored successfully",
                    extra={
                        "stored_as_compressed": stored_as_compressed,
                        "compression_algorithm": compression_algorithm,
                        "stored_path": stored_path.as_posix(),
                        "stored_size": stored_size,
                    },
                )

            except HTTPException as exc:
                _safe_remove_many(tmp_path, compressed_path, final_path)
                await _emit_upload_status(
                    request,
                    username,
                    batch_id,
                    stage="error",
                    filename=logical_name,
                    index=index,
                    total_files=total_files,
                    message=str(exc.detail),
                )
                raise
            except Exception as exc:
                _safe_remove_many(tmp_path, compressed_path, final_path)
                await _emit_upload_status(
                    request,
                    username,
                    batch_id,
                    stage="error",
                    filename=logical_name,
                    index=index,
                    total_files=total_files,
                    message=f"Upload failed: {exc}",
                )
                raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc
            finally:
                await upload.close()

    await broadcast_event(request.app, username, "metadata_update", await storage.metadata_store.load())
    await broadcast_event(
        request.app,
        username,
        "upload_status",
        {
            "batch_id": batch_id,
            "stage": "batch_done",
            "total_files": total_files,
            "stored_files": len(results),
        },
    )
    return JSONResponse(results, status_code=201)


@router.get("/preview/{filename:path}")
async def preview_file(filename: str, request: Request) -> Response:
    return await _serve_stored_file(request, filename, inline=True)


@router.get("/download/{filename:path}")
async def download_file(filename: str, request: Request) -> Response:
    return await _serve_stored_file(request, filename, inline=False)


@router.delete("/delete")
async def delete_files(request: Request, payload: DeleteFilesRequest) -> JSONResponse:
    settings = _settings(request)
    storage_manager = _storage_manager(request)
    username = _get_username(request)

    storage = await storage_manager.get_existing_storage(username)
    if storage is None:
        return JSONResponse({"deleted": [], "missing": payload.filenames}, status_code=200)

    deleted: list[str] = []
    missing: list[str] = []
    normalized_names: list[str] = []
    seen: set[str] = set()

    for raw_name in payload.filenames:
        logical_name = _normalize_uploaded_name(raw_name, settings.max_filename_depth)
        if logical_name in seen:
            continue
        seen.add(logical_name)
        normalized_names.append(logical_name)

    async with storage.file_lock:
        meta = await storage.metadata_store.load()

        for logical_name in normalized_names:
            file_meta = meta.get(logical_name)
            if file_meta is None:
                missing.append(logical_name)
                continue

            stored_path_value = file_meta.get("stored_path")
            if isinstance(stored_path_value, str) and stored_path_value:
                _safe_remove(Path(stored_path_value))

            meta.pop(logical_name, None)
            deleted.append(logical_name)

        await storage.metadata_store.save(meta)

    if deleted:
        await broadcast_event(request.app, username, "metadata_update", await storage.metadata_store.load())

    return JSONResponse({"deleted": deleted, "missing": missing}, status_code=200)


@router.delete("/delete/{filename:path}")
async def delete_file(filename: str, request: Request) -> JSONResponse:
    settings = _settings(request)
    payload = DeleteFilesRequest(filenames=[_normalize_uploaded_name(filename, settings.max_filename_depth)])
    return await delete_files(request, payload)
