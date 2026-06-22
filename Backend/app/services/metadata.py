from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from app.models import FileMetadata
from utils import decode_key, encode_key


class MetadataStore:
    def __init__(self, meta_file: Path) -> None:
        self._meta_file = meta_file

    @property
    def meta_file(self) -> Path:
        return self._meta_file

    async def ensure_initialized(self) -> None:
        self._meta_file.parent.mkdir(parents=True, exist_ok=True)
        if not self._meta_file.exists():
            await self._write_to_disk({})
    async def _read_from_disk(self) -> dict[str, FileMetadata]:
        if not self._meta_file.exists():
            return {}

        def read_sync() -> str:
            try:
                return self._meta_file.read_text(encoding="utf-8")
            except FileNotFoundError:
                return ""

        data = await asyncio.to_thread(read_sync)

        if not data.strip():
            return {}

        try:
            raw: dict[str, Any] = json.loads(data)
        except json.JSONDecodeError:
            return {}

        result: dict[str, FileMetadata] = {}
        for key, value in raw.items():
            if isinstance(value, dict):
                result[decode_key(key)] = cast(FileMetadata, value)

        return result

    async def _write_to_disk(self, meta: dict[str, FileMetadata]) -> None:
        self._meta_file.parent.mkdir(parents=True, exist_ok=True)

        encoded = {encode_key(k): v for k, v in meta.items()}
        payload = json.dumps(encoded, ensure_ascii=False, indent=2)

        tmp_file = self._meta_file.with_name(
            f"{self._meta_file.stem}.{uuid4().hex}{self._meta_file.suffix}.tmp"
        )

        def write_tmp_sync() -> None:
            with open(tmp_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())

        await asyncio.to_thread(write_tmp_sync)

        delay = 0.05
        last_exc: PermissionError | None = None

        for attempt in range(8):
            try:
                await asyncio.to_thread(os.replace, tmp_file, self._meta_file)
                return
            except PermissionError as exc:
                last_exc = exc
                if attempt == 7:
                    break
                await asyncio.sleep(delay)
                delay = min(delay * 2, 0.5)
            except FileNotFoundError:
                break

        with contextlib.suppress(FileNotFoundError):
            tmp_file.unlink()

        if last_exc is not None:
            raise last_exc

    async def load(self) -> dict[str, FileMetadata]:
        return await self._read_from_disk()

    async def save(self, meta: dict[str, FileMetadata]) -> None:
        await self._write_to_disk(meta)

    async def delete(self, filename: str) -> None:
        meta = await self._read_from_disk()
        meta.pop(filename, None)
        await self._write_to_disk(meta)

    async def upsert(
        self,
        filename: str,
        entry: FileMetadata,
    ) -> FileMetadata | None:
        meta = await self._read_from_disk()
        previous = meta.get(filename)
        meta[filename] = entry
        await self._write_to_disk(meta)
        return previous
