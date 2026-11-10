from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import HTTPException


def normalize_name(raw_name: str, max_depth: int) -> str:
    name = raw_name.replace("\\", "/").strip() or "file"
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in name:
        raise HTTPException(400, "Invalid filename")
    if any(
        ord(char) < 32 or 127 <= ord(char) <= 159 or 0xD800 <= ord(char) <= 0xDFFF
        for char in raw_name
    ):
        raise HTTPException(400, "Invalid filename")
    if (
        len(path.parts) > max_depth
        or len(name.encode()) > 4096
        or any(len(part.encode()) > 255 for part in path.parts)
    ):
        raise HTTPException(400, "Filename is too long or nested too deep")
    return path.as_posix() if path.parts else "file"


def content_disposition(disposition: str, logical_name: str) -> str:
    name = PurePosixPath(logical_name).name
    fallback = name.encode("ascii", "ignore").decode().replace('"', "'").strip() or "file"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"
