from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from app.services.file_lock import AsyncFileLock
from app.services.metadata import MetadataStore
from utils import encode_key


@dataclass(slots=True)
class UserStorage:
    username: str
    root_dir: Path
    metadata_file: Path
    metadata_store: MetadataStore
    file_lock: AsyncFileLock
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    deleted: bool = False


class UserStorageManager:
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root
        self._registry_lock = asyncio.Lock()
        self._storages: dict[str, UserStorage] = {}

    def _user_key(self, username: str) -> str:
        normalized = username.strip()
        if not normalized:
            raise ValueError("Username is empty")
        return encode_key(normalized)

    def _build_storage_paths(self, username: str) -> tuple[Path, Path, Path]:
        safe_key = self._user_key(username)
        root_dir = self._storage_root / safe_key
        metadata_file = root_dir / "metadata.json"
        lock_file = root_dir / ".storage.lock"
        return root_dir, metadata_file, lock_file

    async def get_storage(self, username: str) -> UserStorage:
        normalized = username.strip()
        if not normalized:
            raise ValueError("Username is empty")

        async with self._registry_lock:
            storage = self._storages.get(normalized)
            if storage is None:
                root_dir, metadata_file, lock_file = self._build_storage_paths(normalized)
                storage = UserStorage(
                    username=normalized,
                    root_dir=root_dir,
                    metadata_file=metadata_file,
                    metadata_store=MetadataStore(metadata_file),
                    file_lock=AsyncFileLock(lock_file),
                )
                self._storages[normalized] = storage
            return storage

    async def ensure_user_storage(self, username: str) -> UserStorage:
        storage = await self.get_storage(username)

        async with storage.file_lock:
            if storage.deleted:
                storage.deleted = False

            await asyncio.to_thread(storage.root_dir.mkdir, parents=True, exist_ok=True)
            await storage.metadata_store.ensure_initialized()
            return storage

    async def get_existing_storage(self, username: str) -> UserStorage | None:
        storage = await self.get_storage(username)

        if storage.deleted:
            return None

        if not storage.root_dir.exists():
            return None

        return storage

    @staticmethod
    def _make_writable(path: Path) -> None:
        with contextlib.suppress(OSError):
            current_mode = path.stat().st_mode
            path.chmod(current_mode | stat.S_IWUSR | stat.S_IREAD)

    @classmethod
    def _remove_path_sync(cls, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return

        if path.is_file() or path.is_symlink():
            cls._make_writable(path)
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            return

        def _onerror(func, target, exc_info):
            target_path = Path(target)
            cls._make_writable(target_path)
            with contextlib.suppress(Exception):
                func(target)
            if target_path.exists():
                raise exc_info[1]

        shutil.rmtree(path, onerror=_onerror)

    async def delete_user_storage(self, username: str) -> bool:
        storage = await self.get_storage(username)

        root_dir = storage.root_dir
        metadata_file = storage.metadata_file
        lock_file = storage.file_lock.path

        async with storage.file_lock:
            if storage.deleted:
                return True
            storage.deleted = True

        delay = 0.05
        last_exc: OSError | None = None

        def purge_sync() -> None:
            self._remove_path_sync(metadata_file)
            self._remove_path_sync(lock_file)
            self._remove_path_sync(root_dir)

        for attempt in range(10):
            try:
                await asyncio.to_thread(purge_sync)
                break
            except FileNotFoundError:
                break
            except PermissionError as exc:
                last_exc = exc
                if attempt == 9:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 2, 0.75)
            except OSError as exc:
                last_exc = exc
                if attempt == 9:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 2, 0.75)

        async with self._registry_lock:
            self._storages.pop(storage.username, None)

        if metadata_file.exists() or root_dir.exists() or lock_file.exists():
            return False

        if last_exc is not None and (metadata_file.exists() or root_dir.exists() or lock_file.exists()):
            return False

        return True

    async def cleanup_missing(self, username: str) -> None:
        storage = await self.get_storage(username)
        if not storage.root_dir.exists():
            async with self._registry_lock:
                self._storages.pop(storage.username, None)
