from __future__ import annotations

import io
import struct
import tarfile
import zipfile
from collections.abc import Generator, Iterator
from contextlib import closing, contextmanager
from typing import BinaryIO

import rarfile  # type: ignore[import-untyped]

from app.core.settings import MIB

MAX_INDEX_BYTES = 8 * MIB
MAX_ENTRIES = 10_000
ZIP_MIME = "application/zip"
TAR_MIME = "application/x-tar"
RAR_MIME = "application/vnd.rar"
ARCHIVE_MIMES = {ZIP_MIME, TAR_MIME, RAR_MIME}
_END = struct.Struct("<4s4H2LH")
_LOCATOR = struct.Struct("<4sLQL")
_END64 = struct.Struct("<4sQ2H2L4Q")


class ArchiveError(ValueError):
    pass


def _check_zip_index(source: BinaryIO) -> None:
    size = source.seek(0, io.SEEK_END)
    tail_start = max(0, size - _END.size - 65535)
    source.seek(tail_start)
    tail = source.read(size - tail_start)
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0 or len(tail) - pos < _END.size:
        raise ArchiveError("ZIP directory is missing")
    _, disk, start_disk, disk_count, count, index_size, offset, comment = _END.unpack_from(
        tail, pos
    )
    if disk or start_disk or disk_count != count or pos + _END.size + comment != len(tail):
        raise ArchiveError("Unsupported ZIP structure")
    boundary = tail_start + pos
    locator_at = boundary - _LOCATOR.size
    if locator_at >= 0:
        source.seek(locator_at)
        marker, record_disk, record_offset, disks = _LOCATOR.unpack(source.read(_LOCATOR.size))
        if marker == b"PK\x06\x07":
            if record_disk or disks != 1 or record_offset > locator_at - _END64.size:
                raise ArchiveError("Invalid ZIP64 directory")
            source.seek(record_offset)
            record = _END64.unpack(source.read(_END64.size))
            marker, record_size, _, _, disk, start_disk, disk_count, count, index_size, offset = (
                record
            )
            if marker != b"PK\x06\x06" or disk or start_disk or disk_count != count:
                raise ArchiveError("Invalid ZIP64 directory")
            if record_size != 44 or record_offset + _END64.size != locator_at:
                raise ArchiveError("Invalid ZIP64 directory size")
            boundary = record_offset
    if count > MAX_ENTRIES or index_size > MAX_INDEX_BYTES or offset + index_size > boundary:
        raise ArchiveError("ZIP index is outside preview limits")


@contextmanager
def indexed_zip(source: BinaryIO) -> Iterator[zipfile.ZipFile]:
    try:
        _check_zip_index(source)
        with zipfile.ZipFile(source) as archive:
            if len(archive.infolist()) > MAX_ENTRIES:
                raise ArchiveError("ZIP has too many entries")
            yield archive
    except (zipfile.BadZipFile, UnicodeError, struct.error) as exc:
        raise ArchiveError("Invalid ZIP archive") from exc


class BoundedReader(io.RawIOBase):
    def __init__(self, source: BinaryIO, budget: int = MAX_INDEX_BYTES) -> None:
        self.source = source
        self.remaining = budget

    def read(self, size: int = -1) -> bytes:
        if size < 0 or size > self.remaining:
            raise ArchiveError("Archive metadata exceeds preview limits")
        data = self.source.read(size)
        self.remaining -= len(data)
        return data

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self.source.seek(offset, whence)

    def tell(self) -> int:
        return self.source.tell()


def _entry(
    name: str, size: int, packed: int | None, kind: str, encrypted: bool = False
) -> dict[str, object]:
    clean = "".join(char if char.isprintable() else "\ufffd" for char in name[:1024])
    return {
        "name": clean,
        "size": max(0, size),
        "packed": packed,
        "type": kind,
        "encrypted": encrypted,
    }


def _zip_entries(source: BinaryIO) -> Generator[dict[str, object], None, None]:
    with indexed_zip(source) as archive:
        for entry in archive.infolist():
            mode = (entry.external_attr >> 16) & 0o170000
            kind = "folder" if entry.is_dir() else "link" if mode == 0o120000 else "file"
            yield _entry(
                entry.filename,
                entry.file_size,
                entry.compress_size,
                kind,
                bool(entry.flag_bits & 1),
            )


def _tar_entries(source: BinaryIO) -> Generator[dict[str, object], None, None]:
    try:
        with tarfile.open(fileobj=BoundedReader(source), mode="r:") as archive:
            for entry in archive:
                kind = (
                    "folder"
                    if entry.isdir()
                    else "link"
                    if entry.issym() or entry.islnk()
                    else "file"
                    if entry.isfile()
                    else "special"
                )
                yield _entry(entry.name, entry.size, None, kind)
    except (tarfile.TarError, EOFError, RecursionError) as exc:
        raise ArchiveError("Invalid TAR archive") from exc


class _Rar3Index(rarfile.RAR3Parser):
    def _parse_subblocks(self, header: object, data: bytes, position: int) -> int:
        return position

    def _read_comment_v3(self, info: object, password: str | None = None) -> None:
        return None


class _Rar5Index(rarfile.RAR5Parser):
    def _load_comment(self, reader: object, info: object) -> None:
        return None


def _rar_entries(source: BinaryIO) -> Generator[dict[str, object], None, None]:
    header_count = 0

    def count_header(header: object) -> None:
        nonlocal header_count
        header_count += 1
        if header_count > MAX_ENTRIES + 64:
            raise ArchiveError("RAR has too many headers")

    try:
        signature = source.read(8)
        if signature.startswith(b"Rar!\x1a\x07\x00"):
            parser_type = _Rar3Index
        elif signature == b"Rar!\x1a\x07\x01\x00":
            parser_type = _Rar5Index
        else:
            raise ArchiveError("Invalid RAR signature")
        parser = parser_type(
            BoundedReader(source), None, True, "utf-8", True, count_header, 0, True
        )
        parser.parse()
        if parser.has_header_encryption():
            raise ArchiveError("RAR directory is encrypted")
        for entry in parser.infolist():
            kind = "folder" if entry.is_dir() else "link" if entry.is_symlink() else "file"
            yield _entry(
                entry.filename,
                entry.file_size,
                entry.compress_size,
                kind,
                entry.needs_password(),
            )
    except (rarfile.Error, EOFError, TypeError, struct.error, UnicodeError) as exc:
        raise ArchiveError("Invalid or unsupported RAR archive") from exc


def archive_index(source: BinaryIO, mime: str) -> dict[str, object]:
    if mime == ZIP_MIME:
        items = _zip_entries(source)
        label = "ZIP"
    elif mime == TAR_MIME:
        items = _tar_entries(source)
        label = "TAR"
    elif mime == RAR_MIME:
        items = _rar_entries(source)
        label = "RAR"
    else:
        raise ArchiveError("Unsupported archive format")
    entries: list[dict[str, object]] = []
    names_size = 0
    with closing(items):
        for entry in items:
            if len(entries) >= MAX_ENTRIES:
                raise ArchiveError("Archive has too many entries")
            names_size += len(str(entry["name"]).encode())
            if names_size > 3 * MIB:
                raise ArchiveError("Archive paths exceed preview limits")
            entries.append(entry)
    return {"format": label, "entries": entries}
