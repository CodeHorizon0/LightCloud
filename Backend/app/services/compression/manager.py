from __future__ import annotations

import bz2
import hashlib
import io
import lzma
import os
import struct
import tempfile
import zlib
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from anyio import to_thread

from .detection import FileProfile, detect_profile_from_bytes, detect_profile_from_path
from .scanner import CompressionScan, scan_bytes, scan_file

FRAME_SIGNATURE = b"SCMP"
FRAME_VERSION = 1

CATEGORY_IDS = {
    "text": 1,
    "binary": 2,
    "executable": 3,
    "image": 4,
    "audio": 5,
    "video": 6,
    "archive": 7,
    "unknown": 8,
}

CATEGORY_NAMES = {value: key for key, value in CATEGORY_IDS.items()}

ALGO_IDS = {
    "copy": 0,
    "zlib": 1,
    "lzma": 2,
    "bz2": 3,
}

ALGO_NAMES = {value: key for key, value in ALGO_IDS.items()}

FRAME_STRUCT = struct.Struct("<4sBBBBQQ16s")
FRAME_SIZE = FRAME_STRUCT.size

DEFAULT_BUFFER_SIZE = 1024 * 1024


class CompressionError(Exception):
    pass


class CompressionFrameError(CompressionError):
    pass


class CompressionLimitError(CompressionError):
    pass


class CompressionIntegrityError(CompressionError):
    pass


@dataclass(slots=True, frozen=True)
class CompressionResult:
    source_path: str
    output_path: str
    profile: FileProfile
    scan: CompressionScan
    algorithm: str
    skipped: bool


def _build_frame(
    category: str,
    algorithm: str,
    original_size: int,
    content_digest: bytes,
    flags: int = 0,
) -> bytes:
    category_id = CATEGORY_IDS.get(category, CATEGORY_IDS["unknown"])
    algo_id = ALGO_IDS[algorithm]
    if len(content_digest) != 16:
        raise ValueError("content_digest must be 16 bytes")
    return FRAME_STRUCT.pack(
        FRAME_SIGNATURE,
        FRAME_VERSION,
        category_id,
        algo_id,
        flags,
        original_size,
        0,
        content_digest,
    )


def _parse_frame(header: bytes) -> tuple[str, str, int, int, bytes]:
    if len(header) < FRAME_SIZE:
        raise CompressionFrameError("Compressed file is too short")

    signature, version, category_id, algo_id, flags, original_size, _reserved, digest = (
        FRAME_STRUCT.unpack(header[:FRAME_SIZE])
    )
    if signature != FRAME_SIGNATURE:
        raise CompressionFrameError("Invalid compression signature")
    if version != FRAME_VERSION:
        raise CompressionFrameError(f"Unsupported compression frame version: {version}")
    if category_id not in CATEGORY_NAMES:
        raise CompressionFrameError(f"Unknown category id: {category_id}")
    if algo_id not in ALGO_NAMES:
        raise CompressionFrameError(f"Unknown algorithm id: {algo_id}")

    return CATEGORY_NAMES[category_id], ALGO_NAMES[algo_id], original_size, flags, digest


def _atomic_replace(dst: Path, writer: Callable[[BinaryIO], None]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=dst.parent, prefix=".compression-", suffix=".part")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            writer(output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def _ensure_regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise CompressionError("Expected a regular source file")


def _compressor(
    algorithm: str, level: int
) -> zlib._Compress | lzma.LZMACompressor | bz2.BZ2Compressor:
    if algorithm == "zlib":
        return zlib.compressobj(level=level)
    if algorithm == "lzma":
        return lzma.LZMACompressor(preset=min(level, 6), check=lzma.CHECK_NONE)
    if algorithm == "bz2":
        return bz2.BZ2Compressor(level)
    raise CompressionError("Unsupported compression algorithm")


def _write_frame(
    source: BinaryIO, output: BinaryIO, category: str, algorithm: str, level: int, skipped: bool
) -> None:
    position = output.tell()
    output.write(bytes(FRAME_SIZE))
    digest = hashlib.blake2b(digest_size=16)
    compressor = None if algorithm == "copy" else _compressor(algorithm, level)
    size = 0
    while chunk := source.read(DEFAULT_BUFFER_SIZE):
        digest.update(chunk)
        size += len(chunk)
        output.write(chunk if compressor is None else compressor.compress(chunk))
    if compressor is not None:
        output.write(compressor.flush())
    output.seek(position)
    output.write(_build_frame(category, algorithm, size, digest.digest(), flags=int(skipped)))


def _payload_chunks(source: BinaryIO, algorithm: str) -> Iterator[bytes]:
    if algorithm == "copy":
        while chunk := source.read(DEFAULT_BUFFER_SIZE):
            yield chunk
        return

    if algorithm == "zlib":
        decoder = zlib.decompressobj()
        data = source.read(DEFAULT_BUFFER_SIZE)
        while data:
            while True:
                part = decoder.decompress(data, DEFAULT_BUFFER_SIZE)
                if part:
                    yield part
                if decoder.eof:
                    if decoder.unused_data or source.read(1):
                        raise CompressionIntegrityError("Trailing bytes in compressed frame")
                    return
                data = decoder.unconsumed_tail
                if not data and len(part) < DEFAULT_BUFFER_SIZE:
                    break
            data = source.read(DEFAULT_BUFFER_SIZE)
    else:
        decoder_other = (
            lzma.LZMADecompressor(memlimit=128 * 1024 * 1024)
            if algorithm == "lzma"
            else bz2.BZ2Decompressor()
        )
        while not decoder_other.eof:
            data = source.read(DEFAULT_BUFFER_SIZE) if decoder_other.needs_input else b""
            if not data and decoder_other.needs_input:
                break
            part = decoder_other.decompress(data, DEFAULT_BUFFER_SIZE)
            if part:
                yield part
        if decoder_other.eof:
            if decoder_other.unused_data or source.read(1):
                raise CompressionIntegrityError("Trailing bytes in compressed frame")
            return

    raise CompressionIntegrityError("Truncated compressed frame")


def read_frame(source: BinaryIO, max_size: int) -> tuple[str, int, bytes]:
    _, algorithm, size, _, digest = _parse_frame(source.read(FRAME_SIZE))
    if size > max_size:
        raise CompressionLimitError("Declared decompressed size exceeds limit")
    return algorithm, size, digest


def decompress_chunks(source: BinaryIO, frame: tuple[str, int, bytes]) -> Iterator[bytes]:
    algorithm, size, expected_digest = frame
    digest = hashlib.blake2b(digest_size=16)
    written = 0
    try:
        for chunk in _payload_chunks(source, algorithm):
            written += len(chunk)
            if written > size:
                raise CompressionLimitError("Decompressed data exceeds declared size")
            digest.update(chunk)
            yield chunk
    except (zlib.error, lzma.LZMAError, EOFError, OSError) as exc:
        raise CompressionIntegrityError("Invalid compressed payload") from exc
    if written != size or digest.digest() != expected_digest:
        raise CompressionIntegrityError("Decompressed data failed integrity validation")


class CompressionManager:
    def __init__(
        self,
        *,
        sample_size: int = DEFAULT_BUFFER_SIZE,
        min_savings_percent: float = 3.0,
        max_source_size: int = 2 * 1024**3,
    ) -> None:
        self.sample_size = sample_size
        self.min_savings_percent = min_savings_percent
        self.max_source_size = max_source_size

    def _analyze_file(
        self, src: Path, filename_hint: str | None
    ) -> tuple[FileProfile, CompressionScan]:
        _ensure_regular_file(src)
        profile = detect_profile_from_path(src, filename_hint=filename_hint)
        scan = scan_file(
            src, profile, sample_size=self.sample_size, min_savings_percent=self.min_savings_percent
        )
        return profile, scan

    async def analyze_path(
        self, src: Path, *, filename_hint: str | None = None
    ) -> tuple[FileProfile, CompressionScan]:
        return await to_thread.run_sync(self._analyze_file, src, filename_hint)

    @staticmethod
    def _select_algorithm(scan: CompressionScan, requested: str) -> str:
        requested = requested.strip().lower()
        if requested in {"", "auto"}:
            return scan.recommended_algorithm if scan.should_compress else "copy"
        if requested == "copy" or requested in scan.candidate_ratios:
            return requested
        raise CompressionError(f"Unsupported compression algorithm: {requested}")

    async def compress_path(
        self,
        src: Path,
        dst: Path | None = None,
        *,
        force: bool = False,
        algorithm: str = "auto",
        filename_hint: str | None = None,
        level: int = 6,
        analysis: tuple[FileProfile, CompressionScan] | None = None,
    ) -> CompressionResult:
        target = dst or src.with_suffix(src.suffix + ".cmp")

        def compress() -> CompressionResult:
            _ensure_regular_file(src)
            if src.stat().st_size > self.max_source_size:
                raise CompressionLimitError("Source file exceeds compression limit")
            if target.exists() and not force:
                raise FileExistsError(target)
            profile, scan = analysis or self._analyze_file(src, filename_hint)
            selected = self._select_algorithm(scan, algorithm)
            skipped = selected == "copy" or not scan.should_compress

            def write(output: BinaryIO) -> None:
                with src.open("rb") as source:
                    _write_frame(source, output, profile.category, selected, level, skipped)

            _atomic_replace(target, write)
            return CompressionResult(str(src), str(target), profile, scan, selected, skipped)

        return await to_thread.run_sync(compress)

    async def decompress_path(
        self,
        src: Path,
        dst: Path | None = None,
        *,
        force: bool = False,
        max_size: int | None = None,
    ) -> Path:
        target = dst or (
            src.with_suffix("") if src.suffix == ".cmp" else src.with_suffix(src.suffix + ".dec")
        )
        limit = self.max_source_size if max_size is None else max_size

        def decompress() -> Path:
            _ensure_regular_file(src)
            if target.exists() and not force:
                raise FileExistsError(target)
            with src.open("rb") as source:
                frame = read_frame(source, limit)

                def write(output: BinaryIO) -> None:
                    for chunk in decompress_chunks(source, frame):
                        output.write(chunk)

                _atomic_replace(target, write)
            return target

        return await to_thread.run_sync(decompress)

    async def stream_decompressed_path(
        self, src: Path, *, max_size: int | None = None
    ) -> AsyncIterator[bytes]:
        limit = self.max_source_size if max_size is None else max_size

        async def stream() -> AsyncIterator[bytes]:
            _ensure_regular_file(src)
            with src.open("rb") as source:
                frame = await to_thread.run_sync(read_frame, source, limit)
                chunks = decompress_chunks(source, frame)
                while (chunk := await to_thread.run_sync(next_chunk, chunks)) is not None:
                    yield chunk

        return stream()

    def _analyze_bytes(
        self, data: bytes, filename_hint: str | None
    ) -> tuple[FileProfile, CompressionScan]:
        profile = detect_profile_from_bytes(data, filename_hint=filename_hint)
        return profile, scan_bytes(data, profile, min_savings_percent=self.min_savings_percent)

    async def analyze_bytes(
        self, data: bytes | bytearray | memoryview, *, filename_hint: str | None = None
    ) -> CompressionScan:
        _, scan = await to_thread.run_sync(self._analyze_bytes, bytes(data), filename_hint)
        return scan

    async def compress_bytes(
        self,
        data: bytes | bytearray | memoryview,
        *,
        algorithm: str = "auto",
        filename_hint: str | None = None,
        level: int = 6,
    ) -> bytes:
        size = data.nbytes if isinstance(data, memoryview) else len(data)
        if size > self.max_source_size:
            raise CompressionLimitError("Source data exceeds compression limit")

        def compress() -> bytes:
            raw = bytes(data)
            profile, scan = self._analyze_bytes(raw, filename_hint)
            selected = self._select_algorithm(scan, algorithm)
            with io.BytesIO(raw) as source, io.BytesIO() as output:
                _write_frame(
                    source,
                    output,
                    profile.category,
                    selected,
                    level,
                    selected == "copy" or not scan.should_compress,
                )
                return output.getvalue()

        return await to_thread.run_sync(compress)

    async def decompress_bytes(
        self, data: bytes | bytearray | memoryview, *, max_size: int | None = None
    ) -> bytes:
        limit = self.max_source_size if max_size is None else max_size

        def decompress() -> bytes:
            with io.BytesIO(data) as source:
                return b"".join(decompress_chunks(source, read_frame(source, limit)))

        return await to_thread.run_sync(decompress)


def next_chunk(chunks: Iterator[bytes]) -> bytes | None:
    return next(chunks, None)
