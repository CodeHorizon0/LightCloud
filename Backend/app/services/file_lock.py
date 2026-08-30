# app/services/file_lock.py
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
    _USE_MSVCRT = True
else:
    import fcntl
    _USE_MSVCRT = False


@dataclass(slots=True)
class AsyncFileLock:
    path: Path
    timeout: float = 30.0
    poll_interval: float = 0.05

    _fd: int | None = None

    def _acquire_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if _USE_MSVCRT:
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_BINARY, 0o644)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                os.close(fd)
                deadline = None if self.timeout <= 0 else time.monotonic() + self.timeout
                while True:
                    time.sleep(self.poll_interval)
                    fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_BINARY, 0o644)
                    try:
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        os.close(fd)
                        if deadline is not None and time.monotonic() >= deadline:
                            raise TimeoutError(f"Timed out acquiring lock: {self.path}")
            self._fd = fd
        else:
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                deadline = None if self.timeout <= 0 else time.monotonic() + self.timeout
                while True:
                    time.sleep(self.poll_interval)
                    fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        os.close(fd)
                        if deadline is not None and time.monotonic() >= deadline:
                            raise TimeoutError(f"Timed out acquiring lock: {self.path}")
            self._fd = fd

    def _release_sync(self) -> None:
        fd = self._fd
        self._fd = None
        if fd is not None:
            with contextlib.suppress(OSError):
                if _USE_MSVCRT:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    async def acquire(self) -> None:
        await asyncio.to_thread(self._acquire_sync)

    async def release(self) -> None:
        await asyncio.to_thread(self._release_sync)

    async def __aenter__(self) -> AsyncFileLock:
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.release()