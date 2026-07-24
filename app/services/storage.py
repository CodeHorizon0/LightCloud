from __future__ import annotations

import asyncio
import contextlib
import shutil
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.services.file_lock import AsyncFileLock
from app.services.metadata import MetadataStore
from utils import encode_key


@dataclass(slots=True)
class UserStorage:
    """Holds all resources for a single user's storage."""
    username: str
    root_dir: Path                      # root directory for user files
    metadata_file: Path                 # path to metadata.json
    metadata_store: MetadataStore       # store for file metadata
    file_lock: AsyncFileLock            # lock for the storage directory
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # internal async lock
    deleted: bool = False               # marked for deletion


class UserStorageManager:
    """
    Manages user storage directories, caches UserStorage objects,
    and handles creation, retrieval, and deletion.
    """

    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root
        self._registry_lock = asyncio.Lock()          # protects _storages dict
        self._storages: dict[str, UserStorage] = {}   # username -> UserStorage

    def _user_key(self, username: str) -> str:
        """Normalize and encode username for safe filesystem use."""
        normalized = username.strip()
        if not normalized:
            raise ValueError("Username is empty")
        return encode_key(normalized)

    def _build_storage_paths(self, username: str) -> tuple[Path, Path, Path]:
        """Return (root_dir, metadata_file, lock_file) for the user."""
        safe_key = self._user_key(username)
        root_dir = self._storage_root / safe_key
        metadata_file = root_dir / "metadata.json"
        lock_file = root_dir / ".storage.lock"
        return root_dir, metadata_file, lock_file

    async def get_storage(self, username: str) -> UserStorage:
        """
        Get (or create) a UserStorage instance for the user.
        Does not ensure the directory exists on disk.
        """
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
        """
        Get the UserStorage and guarantee the directory and metadata exist.
        Resets the deleted flag if previously set.
        """
        storage = await self.get_storage(username)

        async with storage.file_lock:
            if storage.deleted:
                storage.deleted = False

            await asyncio.to_thread(storage.root_dir.mkdir, parents=True, exist_ok=True)
            await storage.metadata_store.ensure_initialized()
            return storage

    async def get_existing_storage(self, username: str) -> UserStorage | None:
        """
        Get the UserStorage only if the directory physically exists
        and the storage is not marked deleted.
        """
        storage = await self.get_storage(username)

        if storage.deleted:
            return None

        if not storage.root_dir.exists():
            return None

        return storage

    @staticmethod
    def _make_writable(path: Path) -> None:
        """Add user read/write permissions to the path (ignore errors)."""
        with contextlib.suppress(OSError):
            current_mode = path.stat().st_mode
            path.chmod(current_mode | stat.S_IWUSR | stat.S_IREAD)

    @classmethod
    def _remove_path_sync(cls, path: Path) -> None:
        """
        Synchronously remove a file, symlink, or directory tree.
        Makes paths writable before removal to avoid permission errors.
        """
        if not path.exists() and not path.is_symlink():
            return

        if path.is_file() or path.is_symlink():
            cls._make_writable(path)
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            return

        # Error handler for shutil.rmtree – tries to make the target writable
        # and then re-raises the exception if the path still exists.
        def _handle_error(func, target, exc_info_or_exc):
            target_path = Path(target)
            cls._make_writable(target_path)
            with contextlib.suppress(Exception):
                func(target)
            if target_path.exists():
                if isinstance(exc_info_or_exc, tuple):
                    raise exc_info_or_exc[1]
                else:
                    raise exc_info_or_exc

        # onexc is available from Python 3.12; onerror is the old name.
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_handle_error)
        else:
            shutil.rmtree(path, onerror=_handle_error)

    async def delete_user_storage(self, username: str) -> bool:
        """
        Delete the user's entire storage directory, metadata, and lock file.
        Returns True if all files are gone, False if anything remains.
        Implements retries with backoff to handle temporary locks.
        """
        storage = await self.get_storage(username)

        root_dir = storage.root_dir
        metadata_file = storage.metadata_file
        lock_file = storage.file_lock.path

        # Mark as deleted while holding the storage lock
        async with storage.file_lock:
            if storage.deleted:
                return True
            storage.deleted = True

        delay = 0.05
        last_exc: OSError | None = None

        def purge_sync() -> None:
            """Delete all files/directories synchronously."""
            self._remove_path_sync(metadata_file)
            self._remove_path_sync(lock_file)
            self._remove_path_sync(root_dir)

        # Retry up to 10 times with exponential backoff
        for attempt in range(10):
            try:
                await asyncio.to_thread(purge_sync)
                break
            except FileNotFoundError:
                break
            except (PermissionError, OSError) as exc:
                last_exc = exc
                if attempt == 9:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 2, 0.75)

        # Remove the cached instance
        async with self._registry_lock:
            self._storages.pop(storage.username, None)

        # Check if everything was actually removed
        if metadata_file.exists() or root_dir.exists() or lock_file.exists():
            return False

        if last_exc is not None and (metadata_file.exists() or root_dir.exists() or lock_file.exists()):
            return False

        return True

    async def cleanup_missing(self, username: str) -> None:
        """
        Remove the cached UserStorage if its root directory no longer exists.
        Useful after external deletion.
        """
        storage = await self.get_storage(username)
        if not storage.root_dir.exists():
            async with self._registry_lock:
                self._storages.pop(storage.username, None)