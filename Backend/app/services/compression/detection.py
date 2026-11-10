from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.compression.extensions import (
    ARCHIVE_EXTENSIONS,
    AUDIO_EXTENSIONS,
    EXECUTABLE_EXTENSIONS,
    LOSSLESS_IMAGE_EXTENSIONS,
    LOSSY_IMAGE_EXTENSIONS,
    MAGIC_SIGNATURES,
    MIME_BY_EXTENSION,
    TEXT_EXTENSIONS,
    VIDEO_EXTENSIONS,
)


@dataclass(slots=True, frozen=True)
class FileProfile:
    mime: str
    category: str
    extension: str
    size: int
    name: str | None = None


def _category_from_extension(ext: str) -> str | None:
    if ext == ".kra":
        return "kra"
    if ext in TEXT_EXTENSIONS:
        return "text"
    if ext in LOSSLESS_IMAGE_EXTENSIONS:
        return "image"
    if ext in LOSSY_IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    if ext in EXECUTABLE_EXTENSIONS:
        return "executable"
    return None


def _category_from_mime(mime: str) -> str:
    if mime.startswith("text/") or mime in {
        "application/json",
        "application/xml",
        "application/yaml",
        "application/sql",
        "application/toml",
    }:
        return "text"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime in {
        "application/zip",
        "application/gzip",
        "application/bzip2",
        "application/xz",
        "application/x-7z-compressed",
        "application/vnd.rar",
        "application/x-tar",
    }:
        return "archive"
    if mime in {
        "application/x-dosexec",
        "application/x-elf",
        "application/x-mach-binary",
        "application/x-msdownload",
    }:
        return "executable"
    return "binary"


def _is_printable_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    printable = 0
    for b in data:
        if b in (9, 10, 13) or 32 <= b <= 126:
            printable += 1
    return printable / len(data)


def _mime_from_magic(header: bytes, ext: str) -> str:
    if header.startswith(b"RIFF"):
        if len(header) >= 12 and header[8:12] == b"WAVE":
            return "audio/wav"
        if len(header) >= 12 and header[8:12] == b"AVI ":
            return "video/x-msvideo"
        if len(header) >= 12 and header[8:12] == b"WEBP":
            return "image/webp"
        return "application/riff"

    for magic, mime in MAGIC_SIGNATURES.items():
        if header.startswith(magic):
            return mime

    if ext in MIME_BY_EXTENSION:
        return MIME_BY_EXTENSION[ext]

    if ext in TEXT_EXTENSIONS and b"\x00" not in header:
        try:
            header.decode("utf-8")
        except UnicodeDecodeError:
            pass
        else:
            return "text/plain"

    if b"\x00" in header:
        return "application/octet-stream"

    try:
        header.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"

    printable_ratio = _is_printable_ratio(header)
    if printable_ratio >= 0.70:
        return "text/plain"
    return "application/octet-stream"


def _profile(header: bytes, name: str | None, size: int) -> FileProfile:
    extension = Path(name).suffix.lower() if name else ""
    mime = _mime_from_magic(header, extension)
    if extension == ".kra" and mime == "application/zip":
        return FileProfile("application/x-krita", "kra", extension, size, name)

    category = _category_from_mime(mime)
    category_by_extension = _category_from_extension(extension)
    if category_by_extension and (
        category == "binary" or extension not in LOSSLESS_IMAGE_EXTENSIONS
    ):
        category = category_by_extension
    return FileProfile(mime, category, extension, size, name)


def detect_profile_from_path(path: str | Path, filename_hint: str | None = None) -> FileProfile:
    candidate = Path(path)
    if not candidate.is_file():
        raise FileNotFoundError(f"File not found: {candidate}")
    with candidate.open("rb") as source:
        return _profile(source.read(512), filename_hint or candidate.name, candidate.stat().st_size)


def detect_profile_from_bytes(
    data: bytes | bytearray | memoryview, filename_hint: str | None = None
) -> FileProfile:
    view = memoryview(data)
    view = view.cast("B") if view.c_contiguous else memoryview(view.tobytes())
    return _profile(bytes(view[:512]), filename_hint, len(view))
