from __future__ import annotations

import asyncio
import errno
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType

from fastapi import HTTPException

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


@dataclass(slots=True)
class AsyncFileLock:
    path: Path
    timeout: float = 30.0
    _fd: int | None = field(default=None, init=False)

    async def __aenter__(self) -> AsyncFileLock:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
        fd = os.open(self.path, flags, 0o600)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        try:
            while True:
                try:
                    if sys.platform == "win32":
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._fd = fd
                    return self
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    if loop.time() >= deadline:
                        raise HTTPException(503, "Storage is busy") from exc
                    await asyncio.sleep(0.05)
        except BaseException:
            os.close(fd)
            raise

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
