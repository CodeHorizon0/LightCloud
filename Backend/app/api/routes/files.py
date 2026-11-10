from __future__ import annotations

from functools import partial

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.core.request_context import Authenticated, session_storage
from app.core.services import get_services
from app.models import DeleteFilesRequest, SyncDeleteRequest
from app.services.downloads import serve_file
from app.services.file_names import normalize_name
from app.services.storage import clean_pending_blobs, commit_storage_change
from app.services.sync import check_revisions
from app.services.uploads import store_upload

router = APIRouter(tags=["files"])


@router.get("/storage/limits")
async def storage_limits(request: Request, session: Authenticated) -> JSONResponse:
    settings = get_services(request).settings
    return JSONResponse(
        {
            "max_file_size": settings.max_file_size,
            "max_batch_size": settings.max_batch_size,
            "max_upload_files": settings.max_upload_files,
            "max_filename_depth": settings.max_filename_depth,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/upload",
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["files"],
                        "properties": {
                            "files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                            }
                        },
                    }
                }
            },
        }
    },
)
async def upload_files(request: Request, session: Authenticated) -> JSONResponse:
    return JSONResponse(await store_upload(request, session), status_code=201)


@router.post("/sync/upload", status_code=201)
async def sync_upload(request: Request, session: Authenticated) -> JSONResponse:
    return JSONResponse(
        await store_upload(request, session, require_revisions=True), status_code=201
    )


@router.delete("/sync/delete")
async def sync_delete(
    request: Request, payload: SyncDeleteRequest, session: Authenticated
) -> dict[str, list[str]]:
    return await delete_files(request, payload, session)


@router.head("/preview/{filename:path}", include_in_schema=False)
@router.get("/preview/{filename:path}")
async def preview_file(filename: str, request: Request, session: Authenticated) -> Response:
    return await serve_file(request, session, filename, inline=True)


@router.head("/download/{filename:path}", include_in_schema=False)
@router.get("/download/{filename:path}")
async def download_file(filename: str, request: Request, session: Authenticated) -> Response:
    return await serve_file(request, session, filename, inline=False)


@router.delete("/delete")
async def delete_files(
    request: Request, payload: DeleteFilesRequest, session: Authenticated
) -> dict[str, list[str]]:
    services = get_services(request)
    settings = services.settings
    names = list(
        dict.fromkeys(
            normalize_name(name, settings.max_filename_depth) for name in payload.filenames
        )
    )

    async with session_storage(request, session) as storage:
        metadata = await storage.metadata_store.load(names)
        if isinstance(payload, SyncDeleteRequest):
            check_revisions(metadata, names, payload.revisions)
        deleted = [name for name in names if name in metadata]
        missing = [name for name in names if name not in metadata]
        if deleted:
            await commit_storage_change(
                services.events,
                session.user.id,
                partial(storage.metadata_store.commit, {}, deleted),
            )
            await clean_pending_blobs(storage)
    return {"deleted": deleted, "missing": missing}


@router.delete("/delete/{filename:path}")
async def delete_file(
    filename: str, request: Request, session: Authenticated
) -> dict[str, list[str]]:
    return await delete_files(request, DeleteFilesRequest(filenames=[filename]), session)
