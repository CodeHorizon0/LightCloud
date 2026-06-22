from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".csv", ".tsv", ".log", ".json", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".py",
    ".java", ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".rb", ".php", ".sql",
    ".ini", ".cfg", ".toml", ".env", ".sh", ".bat", ".ps1",
}

LOSSLESS_IMAGE_EXTENSIONS = {".png", ".bmp", ".tif", ".tiff", ".gif", ".ico", ".avif", ".webp"}
LOSSY_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".jpe", ".jfif"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".avi", ".wmv", ".mpg", ".mpeg", ".webm", ".flv", ".3gp", ".3g2"}
AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".aac", ".m4a", ".ogg", ".opus", ".wma"}
ARCHIVE_EXTENSIONS = {".zip", ".gz", ".bz2", ".xz", ".7z", ".rar", ".tar", ".tgz", ".tbz2", ".txz"}
EXECUTABLE_EXTENSIONS = {".exe", ".dll", ".sys", ".com", ".scr", ".bin", ".so", ".dylib", ".app", ".o", ".a", ".elf"}

MIME_BY_EXTENSION = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".rst": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".log": "text/plain",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".xml": "application/xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".jsx": "application/javascript",
    ".ts": "application/typescript",
    ".tsx": "application/typescript",
    ".py": "text/x-python",
    ".java": "text/plain",
    ".c": "text/plain",
    ".cpp": "text/plain",
    ".h": "text/plain",
    ".hpp": "text/plain",
    ".rs": "text/plain",
    ".go": "text/plain",
    ".rb": "text/plain",
    ".php": "text/plain",
    ".sql": "application/sql",
    ".ini": "text/plain",
    ".cfg": "text/plain",
    ".toml": "application/toml",
    ".env": "text/plain",
    ".sh": "application/x-sh",
    ".bat": "application/x-dosexec",
    ".ps1": "text/plain",
    ".png": "image/png",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".avif": "image/avif",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jpe": "image/jpeg",
    ".jfif": "image/jpeg",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".wmv": "video/x-ms-wmv",
    ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg",
    ".webm": "video/webm",
    ".flv": "video/x-flv",
    ".3gp": "video/3gpp",
    ".3g2": "video/3gpp2",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".wma": "audio/x-ms-wma",
    ".zip": "application/zip",
    ".gz": "application/gzip",
    ".bz2": "application/bzip2",
    ".xz": "application/xz",
    ".7z": "application/x-7z-compressed",
    ".rar": "application/vnd.rar",
    ".tar": "application/x-tar",
    ".tgz": "application/gzip",
    ".tbz2": "application/bzip2",
    ".txz": "application/xz",
    ".exe": "application/x-dosexec",
    ".dll": "application/x-dosexec",
    ".sys": "application/x-dosexec",
    ".com": "application/x-dosexec",
    ".scr": "application/x-dosexec",
    ".bin": "application/octet-stream",
    ".so": "application/x-elf",
    ".dylib": "application/x-mach-binary",
    ".elf": "application/x-elf",
}

MAGIC_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"BM": "image/bmp",
    b"II*\x00": "image/tiff",
    b"MM\x00*": "image/tiff",
    b"\x00\x00\x01\x00": "image/x-icon",
    b"RIFF": "application/riff",
    b"MZ": "application/x-dosexec",
    b"\x7fELF": "application/x-elf",
    b"\xfe\xed\xfa\xce": "application/x-mach-binary",
    b"\xfe\xed\xfa\xcf": "application/x-mach-binary",
    b"\xcf\xfa\xed\xfe": "application/x-mach-binary",
    b"\xca\xfe\xba\xbe": "application/x-mach-binary",
    b"PK\x03\x04": "application/zip",
    b"PK\x05\x06": "application/zip",
    b"PK\x07\x08": "application/zip",
    b"BZh": "application/bzip2",
    b"\xfd7zXZ\x00": "application/xz",
    b"\x1f\x8b": "application/gzip",
    b"7z\xbc\xaf'\x1c": "application/x-7z-compressed",
}

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

    return FileProfile(
        mime=mime,
        category=category,
        extension=ext,
        size=len(raw),
        name=filename_hint,
    )
