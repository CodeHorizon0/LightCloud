from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from time import time_ns
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.db.database import UserDatabase
from app.models import FileMetadata, FileRecord, PendingBlob, StorageState
from app.services.code_languages import code_language
from app.services.preview_policy import file_revision, preview_policy

type Metadata = dict[str, FileMetadata]


@dataclass(frozen=True, slots=True)
class MetadataSnapshot:
    stamp: int
    data: str


def record_metadata(row: FileRecord) -> FileMetadata:
    return {
        "stored_path": row.stored_path,
        "stored_as_compressed": row.stored_as_compressed,
        "compression_algorithm": row.compression_algorithm,
        "original_size": row.original_size,
        "stored_size": row.stored_size,
        "compression_percent": row.compression_percent,
        "mime": row.mime,
        "category": row.category,
        "preview_profiled": row.preview_profiled,
    }


def record_values(user_id: UUID, path: str, entry: FileMetadata) -> dict[str, object]:
    logical = PurePosixPath(path)
    return {
        "user_id": user_id,
        "path": path,
        "parent_path": "" if logical.parent.as_posix() == "." else logical.parent.as_posix(),
        "name": logical.name,
        **entry,
        "preview_profiled": entry.get("preview_profiled", False),
        "modified_at": time_ns(),
    }


def batches[T](values: list[T], size: int = 500) -> Iterator[list[T]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


class MetadataStore:
    def __init__(self, database: UserDatabase, user_id: UUID) -> None:
        self.database = database
        self.user_id = user_id

    async def _rows(self, session: AsyncSession, names: list[str] | None = None) -> Metadata:
        if names is not None and len(names) > 500:
            result: Metadata = {}
            for chunk in batches(names):
                result.update(await self._rows(session, chunk))
            return result
        query = select(FileRecord).where(col(FileRecord.user_id) == self.user_id)
        if names is not None:
            if not names:
                return {}
            query = query.where(col(FileRecord.path).in_(names))
        rows = await session.scalars(query.order_by(FileRecord.path))
        return {row.path: record_metadata(row) for row in rows}

    async def load(self, names: list[str] | None = None) -> Metadata:
        async with self.database.sessions() as session:
            return await self._rows(session, names)

    async def get(self, name: str) -> FileMetadata | None:
        async with self.database.sessions() as session:
            row = await session.get(FileRecord, (self.user_id, name))
            return record_metadata(row) if row is not None else None

    async def snapshot(self, previous: MetadataSnapshot | None) -> MetadataSnapshot:
        async with self.database.sessions() as session:
            revision = await session.scalar(
                select(StorageState.revision).where(col(StorageState.user_id) == self.user_id)
            )
            if revision is None:
                raise HTTPException(401, "Account storage no longer exists")
            if previous is not None and revision == previous.stamp:
                return previous
            metadata = await self._rows(session)
        return MetadataSnapshot(revision, json.dumps(public_metadata(metadata), ensure_ascii=True))

    async def check_quota(self, staged: Metadata, max_files: int, max_bytes: int) -> None:
        async with self.database.sessions() as session:
            state = await session.get(StorageState, self.user_id)
            if state is None:
                raise HTTPException(401, "Invalid account storage")
            replaced = await self._rows(session, list(staged))
            count = state.file_count + len(staged) - len(replaced)
            size = (
                state.quota_bytes
                + sum(max(row["original_size"], row["stored_size"]) for row in staged.values())
                - sum(max(row["original_size"], row["stored_size"]) for row in replaced.values())
            )
            if count > max_files or size > max_bytes:
                raise HTTPException(507, "Account storage quota exceeded")

    async def _save(self, session: AsyncSession, staged: Metadata, deleted: list[str]) -> None:
        previous = await self._rows(session, list(dict.fromkeys([*staged, *deleted])))
        obsolete = {row["stored_path"] for row in previous.values()}
        for chunk in batches(deleted):
            await session.execute(
                delete(FileRecord).where(
                    col(FileRecord.user_id) == self.user_id, col(FileRecord.path).in_(chunk)
                )
            )
        for records in batches(list(staged.items()), 50):
            statement = insert(FileRecord).values(
                [record_values(self.user_id, path, entry) for path, entry in records]
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=["user_id", "path"],
                    set_={
                        name: getattr(statement.excluded, name)
                        for name in FileRecord.model_fields
                        if name not in {"user_id", "path"}
                    },
                )
            )
        await self._queue_blobs(session, list(obsolete))
        for chunk in batches([entry["stored_path"] for entry in staged.values()]):
            await session.execute(
                delete(PendingBlob).where(
                    col(PendingBlob.user_id) == self.user_id,
                    col(PendingBlob.stored_path).in_(chunk),
                )
            )

    async def _queue_blobs(self, session: AsyncSession, names: list[str]) -> None:
        for chunk in batches(names, 50):
            await session.execute(
                insert(PendingBlob)
                .values([{"user_id": self.user_id, "stored_path": name} for name in chunk])
                .on_conflict_do_nothing()
            )

    async def commit(self, staged: Metadata, deleted: list[str] | None = None) -> None:
        async with self.database.write_session() as session:
            await self._save(session, staged, deleted or [])

    async def stage_blobs(self, names: list[str]) -> None:
        async with self.database.write_session() as session:
            await self._queue_blobs(session, names)

    async def pending_blobs(self) -> list[str]:
        async with self.database.sessions() as session:
            return list(
                await session.scalars(
                    select(PendingBlob.stored_path).where(col(PendingBlob.user_id) == self.user_id)
                )
            )

    async def referenced_blobs(self, names: list[str]) -> set[str]:
        result: set[str] = set()
        async with self.database.sessions() as session:
            for chunk in batches(names):
                result.update(
                    await session.scalars(
                        select(FileRecord.stored_path).where(
                            col(FileRecord.user_id) == self.user_id,
                            col(FileRecord.stored_path).in_(chunk),
                        )
                    )
                )
        return result

    async def clear_pending(self, names: list[str]) -> None:
        if names:
            async with self.database.write_session() as session:
                for chunk in batches(names):
                    await session.execute(
                        delete(PendingBlob).where(
                            col(PendingBlob.user_id) == self.user_id,
                            col(PendingBlob.stored_path).in_(chunk),
                        )
                    )

    async def migration_needed(self) -> bool:
        async with self.database.sessions() as session:
            state = await session.get(StorageState, self.user_id)
            return state is not None and not state.legacy_imported

    async def import_legacy(self, metadata: Metadata) -> None:
        async with self.database.write_session() as session:
            state = await session.get(StorageState, self.user_id)
            if state is None or state.legacy_imported:
                return
            if await self._rows(session):
                raise HTTPException(409, "File metadata migration requires an empty account index")
            await self._save(session, metadata, [])
            await session.execute(
                update(StorageState)
                .where(col(StorageState.user_id) == self.user_id)
                .values(legacy_imported=True)
            )


def public_metadata(metadata: Metadata) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for name, entry in metadata.items():
        preview = preview_policy(entry, name)
        data = {
            key: value
            for key, value in entry.items()
            if key not in {"stored_path", "preview_profiled"}
        }
        result[name] = {
            **data,
            "preview_kind": preview.kind if preview else None,
            "code_language": code_language(name) if preview and preview.kind == "text" else None,
            "revision": file_revision(entry),
        }
    return result
