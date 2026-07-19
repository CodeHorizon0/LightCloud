from __future__ import annotations

import asyncio
import contextlib
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AsyncFileLock:
    path: Path
    timeout: float = 30.0
    poll_interval: float = 0.05
    stale_after: float = 6 * 60 * 60

    _fd: int | None = None

    def _write_lock_payload(self, fd: int) -> None:
        payload = f"pid={os.getpid()} ts={time.time()}\n".encode("utf-8")
        os.write(fd, payload)

    def _try_remove_stale_lock(self) -> bool:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            return True

        age = time.time() - stat.st_mtime
        if age < self.stale_after:
            return False

        with contextlib.suppress(FileNotFoundError, PermissionError):
            self.path.unlink()
        return True

    def _acquire_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        deadline = None if self.timeout <= 0 else time.monotonic() + self.timeout

        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            except FileExistsError:
                if self._try_remove_stale_lock():
                    continue

                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out acquiring lock: {self.path}")

                time.sleep(self.poll_interval)
                continue

            try:
                self._write_lock_payload(fd)
            except Exception:
                with contextlib.suppress(OSError, FileNotFoundError):
                    os.close(fd)
                with contextlib.suppress(FileNotFoundError, PermissionError):
                    self.path.unlink()
                raise

            self._fd = fd
            return

    def _release_sync(self) -> None:
        fd = self._fd
        self._fd = None

        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)

        with contextlib.suppress(FileNotFoundError, PermissionError):
            self.path.unlink()

    async def acquire(self) -> None:
        await asyncio.to_thread(self._acquire_sync)

    async def release(self) -> None:
        await asyncio.to_thread(self._release_sync)

    async def __aenter__(self) -> "AsyncFileLock":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.release()
