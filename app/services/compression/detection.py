from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from app.services.compression.extensions import TEXT_EXTENSIONS, LOSSLESS_IMAGE_EXTENSIONS, LOSSY_IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, AUDIO_EXTENSIONS, ARCHIVE_EXTENSIONS, EXECUTABLE_EXTENSIONS, MIME_BY_EXTENSION, MAGIC_SIGNATURES

@dataclass(slots=True, frozen=True)
class FileProfile:
    mime: str
    category: str
    extension: str
    size: int
    name: str | None = None

def _extension(path: Path, filename_hint: str | None = None) -> str:
    if filename_hint:
        return Path(filename_hint).suffix.lower()
    return path.suffix.lower()

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
    if mime.startswith("text/") or mime in {"application/json", "application/xml", "application/yaml", "application/sql", "application/toml"}:
        return "text"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime in {"application/zip", "application/gzip", "application/bzip2", "application/xz", "application/x-7z-compressed", "application/vnd.rar", "application/x-tar"}:
        return "archive"
    if mime in {"application/x-dosexec", "application/x-elf", "application/x-mach-binary", "application/x-msdownload"}:
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

def detect_profile_from_path(path: str | Path, filename_hint: str | None = None) -> FileProfile:
    candidate = Path(path)
    if not candidate.is_file():
        raise FileNotFoundError(f"File not found: {candidate}")

    with candidate.open("rb") as fh:
        header = fh.read(512)

    ext = _extension(candidate, filename_hint)
    mime = _mime_from_magic(header, ext)
    category = _category_from_mime(mime)

    ext_category = _category_from_extension(ext)
    if category == "binary" and ext_category is not None:
        category = ext_category

    if ext in LOSSY_IMAGE_EXTENSIONS:
        category = "image"
    elif ext in VIDEO_EXTENSIONS:
        category = "video"
    elif ext in AUDIO_EXTENSIONS:
        category = "audio"
    elif ext in ARCHIVE_EXTENSIONS:
        category = "archive"
    elif ext in EXECUTABLE_EXTENSIONS:
        category = "executable"
    elif ext in TEXT_EXTENSIONS:
        category = "text"

    if ext == ".kra":
        mime = "application/x-krita"
        category = "kra"

    return FileProfile(
        mime=mime,
        category=category,
        extension=ext,
        size=candidate.stat().st_size,
        name=filename_hint or candidate.name,
    )

def detect_profile_from_bytes(data: bytes | bytearray | memoryview, filename_hint: str | None = None) -> FileProfile:
    raw = bytes(data)
    header = raw[:512]
    ext = _extension(Path(filename_hint or "file"))
    mime = _mime_from_magic(header, ext)
    category = _category_from_mime(mime)

    ext_category = _category_from_extension(ext)
    if category == "binary" and ext_category is not None:
        category = ext_category

    if ext == ".kra":
        mime = "application/x-krita"
        category = "kra"

    return FileProfile(
        mime=mime,
        category=category,
        extension=ext,
        size=len(raw),
        name=filename_hint,
    )