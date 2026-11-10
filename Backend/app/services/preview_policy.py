from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

from app.core.settings import MIB
from app.models import FileMetadata
from app.services.archive_index import ARCHIVE_MIMES, ZIP_MIME, ArchiveError, indexed_zip

type PreviewKind = Literal[
    "image",
    "audio",
    "video",
    "text",
    "markdown",
    "pdf",
    "document",
    "spreadsheet",
    "presentation",
    "krita",
    "archive",
]

MAX_TEXT_BYTES = MIB
MAX_MARKDOWN_BYTES = 256 * 1024
MAX_KRITA_BYTES = 64 * MIB
MAX_PDF_BYTES = 32 * MIB
MAX_OFFICE_BYTES = 24 * MIB
KRITA_MIME = "application/x-krita"
_OFFICE_PREFIX = "application/vnd.openxmlformats-officedocument."
OFFICE_PACKAGES = {
    ".docx": (_OFFICE_PREFIX + "wordprocessingml.document", "word/document.xml"),
    ".xlsx": (_OFFICE_PREFIX + "spreadsheetml.sheet", "xl/workbook.xml"),
    ".pptx": (_OFFICE_PREFIX + "presentationml.presentation", "ppt/presentation.xml"),
}
_MEDIA_MIME = re.compile(r"(image|audio|video)/[a-z0-9][a-z0-9.+-]*")
_TEXT_TYPES = {
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/javascript",
    "application/typescript",
    "application/sql",
    "application/toml",
    "application/yaml",
}


@dataclass(frozen=True, slots=True)
class Preview:
    kind: PreviewKind
    media_type: str


def file_revision(entry: FileMetadata) -> str:
    return hashlib.blake2s(entry["stored_path"].encode(), digest_size=12).hexdigest()


def office_mime(source: BinaryIO) -> str | None:
    try:
        with indexed_zip(source) as archive:
            names = set(archive.namelist())
            if {"[Content_Types].xml", "_rels/.rels"} <= names:
                matches = [mime for mime, marker in OFFICE_PACKAGES.values() if marker in names]
                if len(matches) == 1:
                    return matches[0]
    except ArchiveError:
        pass
    return None


def classify_upload(path: Path, mime: str) -> str:
    if mime == ZIP_MIME or mime.startswith(_OFFICE_PREFIX):
        with path.open("rb") as source:
            return office_mime(source) or (
                ZIP_MIME if mime == ZIP_MIME else "application/octet-stream"
            )
    return mime


def preview_policy(entry: FileMetadata, name: str) -> Preview | None:
    mime = entry["mime"].lower()
    size = entry["original_size"]
    if mime == ZIP_MIME and not entry.get("preview_profiled"):
        package = OFFICE_PACKAGES.get(Path(name).suffix.lower())
        if package is not None:
            mime = package[0]
    if mime.startswith(_OFFICE_PREFIX):
        if size > MAX_OFFICE_BYTES:
            return None
        if mime == OFFICE_PACKAGES[".docx"][0]:
            return Preview("document", mime)
        if mime == OFFICE_PACKAGES[".xlsx"][0]:
            return Preview("spreadsheet", mime)
        if mime == OFFICE_PACKAGES[".pptx"][0]:
            return Preview("presentation", mime)
    if mime in {"text/csv", "text/tab-separated-values"} and size <= MAX_TEXT_BYTES:
        return Preview("spreadsheet", mime)
    if mime in ARCHIVE_MIMES and not entry["stored_as_compressed"]:
        return Preview("archive", "application/json")
    if mime == KRITA_MIME:
        return Preview("krita", "image/jpeg") if size <= MAX_KRITA_BYTES else None
    if mime == "text/markdown":
        return (
            Preview("markdown", "text/plain; charset=utf-8") if size <= MAX_MARKDOWN_BYTES else None
        )
    if mime.startswith("text/") or mime in _TEXT_TYPES:
        return Preview("text", "text/plain; charset=utf-8") if size <= MAX_TEXT_BYTES else None
    if mime == "application/pdf":
        return Preview("pdf", mime) if size <= MAX_PDF_BYTES else None
    if _MEDIA_MIME.fullmatch(mime):
        if mime.startswith("image/"):
            return Preview("image", mime)
        if mime.startswith("audio/"):
            return Preview("audio", mime)
        return Preview("video", mime)
    return None
