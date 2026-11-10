from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import stat
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from time import time_ns
from uuid import UUID

from anyio import CancelScope, to_thread
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import UserDatabase
from app.db.sqlite import fsync_directory
from app.models import User
from app.services.file_lock import AsyncFileLock
from app.services.legacy_metadata import read_legacy_metadata
from app.services.metadata import MetadataStore
from app.services.sse import METADATA_CHANGED, EventBroker
from utils import encode_key

logger = logging.getLogger(__name__)
_BLOB_NAME = re.compile(r"[0-9a-f]{32}(?:_[^/\\:]+|\.cmp)?")


@dataclass(frozen=True, slots=True)
class UserStorage:
    root_dir: Path
    legacy_key: str
    metadata_store: MetadataStore
    lock_path: Path

    def lock(self) -> AsyncFileLock:
        return AsyncFileLock(self.lock_path)

    def blob_path(self, value: object) -> Path | None:
        if not isinstance(value, str):
            return None
        parts = value.replace("\\", "/").split("/")
        leaf = parts[-1]
        if (
            not _BLOB_NAME.fullmatch(leaf)
            or any(ord(char) < 32 or ord(char) == 127 for char in leaf)
            or (sys.platform == "win32" and leaf.endswith((" ", ".")))
            or (len(parts) > 1 and parts[-2] not in {self.root_dir.name, self.legacy_key})
        ):
            return None
        candidate = self.root_dir / leaf
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            return None
        return candidate if stat.S_ISREG(info.st_mode) else None


async def clean_pending_blobs(storage: UserStorage) -> None:
    try:
        await _clean_pending_blobs(storage)
    except (OSError, SQLAlchemyError):
        logger.warning("Blob cleanup deferred until the next access", exc_info=True)


async def _clean_pending_blobs(storage: UserStorage) -> None:
    names = await storage.metadata_store.pending_blobs()
    referenced = await storage.metadata_store.referenced_blobs(names)
    removed: list[str] = []
    for name in names:
        if name in referenced:
            removed.append(name)
            continue
        try:
            path = storage.blob_path(name)
            if path is not None:
                await to_thread.run_sync(path.unlink, True)
            removed.append(name)
        except OSError:
            logger.warning("Could not remove obsolete blob %s", name, exc_info=True)
    if removed:
        if storage.root_dir.exists():
            await to_thread.run_sync(fsync_directory, storage.root_dir)
        await storage.metadata_store.clear_pending(removed)


async def commit_storage_change(
    events: EventBroker, user_id: UUID, write: Callable[[], Awaitable[None]]
) -> None:
    async def commit() -> None:
        await write()
        events.publish(user_id, METADATA_CHANGED)

    with CancelScope(shield=True):
        task = asyncio.create_task(commit())
        interrupted = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                interrupted = True
        task.result()
        if interrupted:
            raise asyncio.CancelledError


class UserStorageManager:
    def __init__(self, storage_root: Path, database: UserDatabase) -> None:
        self.root = storage_root.resolve()
        self.locks = self.root / ".locks"
        self.database = database

    def initialize(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.locks.mkdir(mode=0o700, exist_ok=True)

    async def migrate_all(self) -> None:
        for user in await self.database.storage_maintenance_users():
            storage = self.for_user(user)
            async with storage.lock():
                await self.prepare(storage, user)

    def for_user(self, user: User) -> UserStorage:
        key = f"acct-{user.id.hex}"
        root = self.root / key
        return UserStorage(
            root,
            encode_key(user.username),
            MetadataStore(self.database, user.id),
            self.locks / f"{key}.lock",
        )

    async def prepare(self, storage: UserStorage, user: User, *, create: bool = False) -> None:
        if storage.root_dir.is_symlink() or storage.root_dir.is_junction():
            raise HTTPException(409, "Invalid account storage")
        if storage.root_dir.exists():
            if not storage.root_dir.is_dir():
                raise HTTPException(409, "Invalid account storage")
        elif user.legacy_storage:
            legacy_root = self.root / storage.legacy_key
            legacy_lock = self.locks / f"legacy-{storage.legacy_key.lower()}.lock"
            async with AsyncFileLock(legacy_lock):
                if legacy_root.exists() or legacy_root.is_symlink():
                    await self._migrate_legacy(storage, legacy_root)
        if create:
            storage.root_dir.mkdir(mode=0o700, exist_ok=True)
        await self._import_metadata(storage)
        await clean_pending_blobs(storage)

    async def _import_metadata(self, storage: UserStorage) -> None:
        source = storage.root_dir / "metadata.json"
        if await storage.metadata_store.migration_needed():
            metadata = (
                await to_thread.run_sync(read_legacy_metadata, source) if source.exists() else {}
            )
            for entry in metadata.values():
                path = storage.blob_path(entry["stored_path"])
                if path is None:
                    raise HTTPException(409, "Legacy metadata references a missing or invalid file")
                entry["stored_path"] = path.name
            await storage.metadata_store.import_legacy(metadata)
        if source.exists():
            try:
                archive = source.with_suffix(".json.migrated")
                if archive.exists():
                    archive = source.with_name(f"metadata.json.{time_ns()}.migrated")
                await to_thread.run_sync(source.rename, archive)
                await to_thread.run_sync(fsync_directory, storage.root_dir)
            except OSError:
                logger.warning("Legacy metadata imported but backup rename failed", exc_info=True)

    async def _migrate_legacy(self, storage: UserStorage, legacy_root: Path) -> None:
        if (
            legacy_root.is_symlink()
            or legacy_root.is_junction()
            or not legacy_root.is_dir()
            or legacy_root.resolve().name != storage.legacy_key
        ):
            raise HTTPException(409, "Legacy storage ownership requires verification")
        if os.name == "nt":
            names = await self.database.legacy_usernames()
            aliases = [
                name for name in names if encode_key(name).lower() == storage.legacy_key.lower()
            ]
            if len(aliases) != 1:
                raise HTTPException(409, "Legacy storage ownership requires verification")
        await to_thread.run_sync(legacy_root.rename, storage.root_dir)

    async def purge(self, user_id: UUID) -> None:
        root = self.root / f"acct-{user_id.hex}"
        try:
            await to_thread.run_sync(shutil.rmtree, root)
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("Could not purge account storage for %s", user_id)
            raise HTTPException(500, "Account revoked but storage cleanup failed") from None
