from __future__ import annotations

import asyncio
import bz2
import contextlib
import hashlib
import lzma
import os
import shutil
import struct
import tempfile
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from utils import encode_key

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


def _adaptive_buffer_size(source_size: int, base_buffer_size: int) -> int:
    base = max(256 * 1024, int(base_buffer_size))
    size = max(0, int(source_size))

    if size <= 16 * 1024 * 1024:
        target = 1024 * 1024
    elif size <= 128 * 1024 * 1024:
        target = 2 * 1024 * 1024
    elif size <= 1024 * 1024 * 1024:
        target = 4 * 1024 * 1024
    else:
        target = 8 * 1024 * 1024

    return min(max(base, target), 8 * 1024 * 1024)


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

def _atomic_replace(dst: Path, write_fn) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        dir=str(dst.parent),
        prefix=f".{dst.name}.",
        suffix=".part",
    ) as tmp:
        tmp_path = Path(tmp.name)
        try:
            write_fn(tmp)
            tmp.flush()
            os.fsync(tmp.fileno())
        except Exception:
            with contextlib.suppress(FileNotFoundError, PermissionError):
                tmp_path.unlink()
            raise

    os.replace(tmp_path, dst)
    return dst

def _ensure_regular_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise CompressionError(f"Not a regular file: {path}")
    if path.is_symlink():
        raise CompressionError(f"Symlinks are not allowed: {path}")

def _read_frame(path: Path) -> tuple[str, str, int, int, bytes]:
    with path.open("rb") as fin:
        header = fin.read(FRAME_SIZE)
    return _parse_frame(header)


def _hash_file(path: Path, buffer_size: int = DEFAULT_BUFFER_SIZE) -> bytes:
    digest = hashlib.blake2b(digest_size=16)
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(buffer_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.digest()

def _hash_bytes(data: bytes) -> bytes:
    digest = hashlib.blake2b(digest_size=16)
    digest.update(data)
    return digest.digest()

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

    signature, version, category_id, algo_id, flags, original_size, _reserved, digest = FRAME_STRUCT.unpack(
        header[:FRAME_SIZE]
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

def _compress_payload(
    src: Path,
    out_fh,
    algorithm: str,
    buffer_size: int,
    level: int,
) -> None:
    if algorithm == "copy":
        with src.open("rb") as fin:
            while True:
                chunk = fin.read(buffer_size)
                if not chunk:
                    break
                out_fh.write(chunk)
        return

    if algorithm == "zlib":
        compressor = zlib.compressobj(level=level, wbits=15, memLevel=9)
    elif algorithm == "lzma":
        compressor = lzma.LZMACompressor(preset=level, check=lzma.CHECK_NONE)
    elif algorithm == "bz2":
        compressor = bz2.BZ2Compressor()
    else:
        raise CompressionError(f"Unsupported algorithm: {algorithm}")

    with src.open("rb") as fin:
        while True:
            chunk = fin.read(buffer_size)
            if not chunk:
                break
            piece = compressor.compress(chunk)
            if piece:
                out_fh.write(piece)

        tail = compressor.flush()
        if tail:
            out_fh.write(tail)

def _decompress_payload(
    fin,
    out_fh,
    algorithm: str,
    original_size: int,
    max_size: int,
    buffer_size: int,
    expected_digest: bytes,
) -> None:
    written = 0
    digest = hashlib.blake2b(digest_size=16)

    if algorithm == "copy":
        while True:
            chunk = fin.read(buffer_size)
            if not chunk:
                break
            written += len(chunk)
            if written > max_size:
                raise CompressionLimitError(f"Decompressed data exceeds limit {max_size}")
            digest.update(chunk)
            out_fh.write(chunk)
    else:
        if algorithm == "zlib":
            decompressor = zlib.decompressobj()
        elif algorithm == "lzma":
            decompressor = lzma.LZMADecompressor()
        elif algorithm == "bz2":
            decompressor = bz2.BZ2Decompressor()
        else:
            raise CompressionError(f"Unsupported algorithm: {algorithm}")

        while True:
            chunk = fin.read(buffer_size)
            if not chunk:
                break

            remaining = max_size - written
            if remaining <= 0:
                raise CompressionLimitError(f"Decompressed data exceeds limit {max_size}")

            try:
                piece = decompressor.decompress(chunk, remaining)
            except TypeError:
                piece = decompressor.decompress(chunk)

            if piece:
                written += len(piece)
                if written > max_size:
                    raise CompressionLimitError(f"Decompressed data exceeds limit {max_size}")
                digest.update(piece)
                out_fh.write(piece)

        if algorithm == "zlib":
            tail = decompressor.flush()
            if tail:
                written += len(tail)
                if written > max_size:
                    raise CompressionLimitError(f"Decompressed data exceeds limit {max_size}")
                digest.update(tail)
                out_fh.write(tail)

        if hasattr(decompressor, "eof") and not decompressor.eof:
            raise CompressionIntegrityError("Compressed stream ended prematurely")
        if getattr(decompressor, "unused_data", b""):
            raise CompressionIntegrityError("Trailing garbage found after compressed payload")

    if written != original_size:
        raise CompressionIntegrityError(
            f"Output size mismatch: expected {original_size}, got {written}"
        )
    if digest.digest() != expected_digest:
        raise CompressionIntegrityError("Checksum mismatch after decompression")

def _compress_bytes_payload(raw: bytes, algorithm: str, level: int) -> bytes:
    if algorithm == "copy":
        return raw
    if algorithm == "zlib":
        return zlib.compress(raw, level=level)
    if algorithm == "lzma":
        return lzma.compress(raw, preset=level, check=lzma.CHECK_NONE)
    if algorithm == "bz2":
        return bz2.compress(raw)
    raise CompressionError(f"Unsupported algorithm: {algorithm}")

def _decompress_bytes_payload(raw: bytes, algorithm: str) -> bytes:
    if algorithm == "copy":
        return raw
    if algorithm == "zlib":
        decompressor = zlib.decompressobj()
        output = decompressor.decompress(raw)
        tail = decompressor.flush()
        if tail:
            output += tail
        if getattr(decompressor, "unused_data", b""):
            raise CompressionIntegrityError("Trailing garbage found after compressed payload")
        return output
    if algorithm == "lzma":
        decompressor = lzma.LZMADecompressor()
        output = decompressor.decompress(raw)
        if hasattr(decompressor, "eof") and not decompressor.eof:
            raise CompressionIntegrityError("Compressed stream ended prematurely")
        if getattr(decompressor, "unused_data", b""):
            raise CompressionIntegrityError("Trailing garbage found after compressed payload")
        return output
    if algorithm == "bz2":
        decompressor = bz2.BZ2Decompressor()
        output = decompressor.decompress(raw)
        if getattr(decompressor, "unused_data", b""):
            raise CompressionIntegrityError("Trailing garbage found after compressed payload")
        return output
    raise CompressionError(f"Unsupported algorithm: {algorithm}")

class CompressionManager:
    def __init__(
        self,
        work_root: Path,
        *,
        sample_size: int = 1024 * 1024,
        min_savings_percent: float = 3.0,
        max_source_size: int = 2 * 1024 * 1024 * 1024,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
    ) -> None:
        self.work_root = work_root
        self.sample_size = max(64 * 1024, int(sample_size))
        self.min_savings_percent = float(min_savings_percent)
        self.max_source_size = int(max_source_size)
        self.buffer_size = int(buffer_size)

    def _safe_username(self, username: str) -> str:
        normalized = username.strip()
        if not normalized:
            raise CompressionError("Username is empty")
        return encode_key(normalized)

    def make_job_dir(self, username: str) -> Path:
        user_key = self._safe_username(username)
        return self.work_root / user_key / uuid.uuid4().hex

    async def ensure_work_root(self) -> None:
        await asyncio.to_thread(self.work_root.mkdir, parents=True, exist_ok=True)

    async def prepare_job_dir(self, username: str) -> Path:
        await self.ensure_work_root()
        job_dir = self.make_job_dir(username)
        await asyncio.to_thread(job_dir.mkdir, parents=True, exist_ok=False)
        return job_dir

    async def cleanup_path(self, path: Path) -> None:
        def _cleanup() -> None:
            if path.is_file() or path.is_symlink():
                with contextlib.suppress(FileNotFoundError, PermissionError):
                    path.unlink()
            elif path.is_dir():
                with contextlib.suppress(FileNotFoundError, PermissionError):
                    shutil.rmtree(path)

        await asyncio.to_thread(_cleanup)

    async def analyze_path(self, src: Path, *, filename_hint: str | None = None) -> CompressionScan:
        _ensure_regular_file(src)
        profile = detect_profile_from_path(src, filename_hint=filename_hint)
        return await asyncio.to_thread(
            scan_file,
            src,
            profile,
            sample_size=self.sample_size,
            min_savings_percent=self.min_savings_percent,
        )

    async def compress_path(
        self,
        src: Path,
        dst: Path | None = None,
        *,
        force: bool = False,
        algorithm: str = "auto",
        filename_hint: str | None = None,
        level: int = 6,
    ) -> CompressionResult:
        _ensure_regular_file(src)
        size = src.stat().st_size
        if size > self.max_source_size:
            raise CompressionLimitError(
                f"Source file exceeds limit {self.max_source_size} bytes"
            )

        profile = detect_profile_from_path(src, filename_hint=filename_hint)
        scan = await asyncio.to_thread(
            scan_file,
            src,
            profile,
            sample_size=self.sample_size,
            min_savings_percent=self.min_savings_percent,
        )

        selected = self._select_algorithm(profile, scan, algorithm)
        skipped = selected == "copy" or not scan.should_compress

        if dst is None:
            dst = src.with_suffix(src.suffix + ".cmp")

        if dst.exists() and not force:
            raise FileExistsError(f"Output file already exists: {dst}")

        buffer_size = _adaptive_buffer_size(size, self.buffer_size)
        digest = await asyncio.to_thread(_hash_file, src, buffer_size)
        frame = _build_frame(
            profile.category,
            selected,
            size,
            digest,
            flags=1 if skipped else 0,
        )

        def _writer(out_fh) -> None:
            out_fh.write(frame)
            _compress_payload(src, out_fh, selected, buffer_size, level)

        await asyncio.to_thread(_atomic_replace, dst, _writer)
        return CompressionResult(
            source_path=str(src),
            output_path=str(dst),
            profile=profile,
            scan=scan,
            algorithm=selected,
            skipped=skipped,
        )

    async def decompress_path(
        self,
        src: Path,
        dst: Path | None = None,
        *,
        force: bool = False,
        max_size: int | None = None,
    ) -> Path:
        _ensure_regular_file(src)
        limit = self.max_source_size if max_size is None else int(max_size)

        category, algorithm, original_size, flags, digest = await asyncio.to_thread(_read_frame, src)
        if original_size > limit:
            raise CompressionLimitError(f"Declared decompressed size exceeds limit {limit}")

        if dst is None:
            if src.suffix == ".cmp":
                dst = src.with_suffix("")
            else:
                dst = src.with_suffix(src.suffix + ".dec")

        if dst.exists() and not force:
            raise FileExistsError(f"Output file already exists: {dst}")

        buffer_size = _adaptive_buffer_size(max(original_size, src.stat().st_size), self.buffer_size)

        def _writer(out_fh) -> None:
            with src.open("rb") as fin:
                fin.seek(FRAME_SIZE)
                _decompress_payload(
                    fin,
                    out_fh,
                    algorithm,
                    original_size,
                    limit,
                    buffer_size,
                    digest,
                )

        await asyncio.to_thread(_atomic_replace, dst, _writer)
        return dst

    async def stream_decompressed_path(
        self,
        src: Path,
        *,
        max_size: int | None = None,
    ) -> AsyncIterator[bytes]:
        _ensure_regular_file(src)
        limit = self.max_source_size if max_size is None else int(max_size)
        category, algorithm, original_size, flags, digest = await asyncio.to_thread(_read_frame, src)
        if original_size > limit:
            raise CompressionLimitError(f"Declared decompressed size exceeds limit {limit}")

        buffer_size = _adaptive_buffer_size(max(original_size, src.stat().st_size), self.buffer_size)

        async def _iterator() -> AsyncIterator[bytes]:
            written = 0
            digest_calc = hashlib.blake2b(digest_size=16)

            with src.open("rb") as fin:
                fin.seek(FRAME_SIZE)

                if algorithm == "copy":
                    while True:
                        chunk = await asyncio.to_thread(fin.read, buffer_size)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > limit:
                            raise CompressionLimitError(f"Decompressed data exceeds limit {limit}")
                        digest_calc.update(chunk)
                        yield chunk
                else:
                    if algorithm == "zlib":
                        decompressor = zlib.decompressobj()
                    elif algorithm == "lzma":
                        decompressor = lzma.LZMADecompressor()
                    elif algorithm == "bz2":
                        decompressor = bz2.BZ2Decompressor()
                    else:
                        raise CompressionError(f"Unsupported algorithm: {algorithm}")

                    while True:
                        chunk = await asyncio.to_thread(fin.read, buffer_size)
                        if not chunk:
                            break

                        remaining = limit - written
                        if remaining <= 0:
                            raise CompressionLimitError(f"Decompressed data exceeds limit {limit}")

                        try:
                            piece = decompressor.decompress(chunk, remaining)
                        except TypeError:
                            piece = decompressor.decompress(chunk)

                        if piece:
                            written += len(piece)
                            if written > limit:
                                raise CompressionLimitError(f"Decompressed data exceeds limit {limit}")
                            digest_calc.update(piece)
                            yield piece

                    if algorithm == "zlib":
                        tail = decompressor.flush()
                        if tail:
                            written += len(tail)
                            if written > limit:
                                raise CompressionLimitError(f"Decompressed data exceeds limit {limit}")
                            digest_calc.update(tail)
                            yield tail

                    if hasattr(decompressor, "eof") and not decompressor.eof:
                        raise CompressionIntegrityError("Compressed stream ended prematurely")
                    if getattr(decompressor, "unused_data", b""):
                        raise CompressionIntegrityError("Trailing garbage found after compressed payload")

                if written != original_size:
                    raise CompressionIntegrityError(
                        f"Output size mismatch: expected {original_size}, got {written}"
                    )
                if digest_calc.digest() != digest:
                    raise CompressionIntegrityError("Checksum mismatch after decompression")

        return _iterator()


    def _select_algorithm(self, profile: FileProfile, scan: CompressionScan, requested: str) -> str:
        requested = (requested or "auto").strip().lower()

        if requested not in {"auto", "copy", "zlib", "lzma", "bz2"}:
            raise CompressionError(f"Unsupported algorithm request: {requested}")

        if requested != "auto":
            if requested == "copy":
                return "copy"
            if requested not in scan.candidate_ratios:
                raise CompressionError(
                    f"Algorithm {requested} is not supported for {profile.category}"
                )
            return requested

        if not scan.should_compress:
            return "copy"
        return scan.recommended_algorithm

    async def compress_bytes(
        self,
        data: bytes | bytearray | memoryview,
        *,
        algorithm: str = "auto",
        filename_hint: str | None = None,
        level: int = 6,
    ) -> bytes:
        raw = bytes(data)
        if len(raw) > self.max_source_size:
            raise CompressionLimitError(
                f"Source data exceeds limit {self.max_source_size} bytes"
            )
        profile = detect_profile_from_bytes(raw, filename_hint=filename_hint)
        scan = await asyncio.to_thread(
            scan_bytes,
            raw,
            profile,
            min_savings_percent=self.min_savings_percent,
        )
        selected = self._select_algorithm(profile, scan, algorithm)
        digest = _hash_bytes(raw)
        frame = _build_frame(
            profile.category,
            selected,
            len(raw),
            digest,
            flags=1 if selected == "copy" or not scan.should_compress else 0,
        )
        payload = _compress_bytes_payload(raw, selected, level)
        return frame + payload

    async def decompress_bytes(
        self,
        data: bytes | bytearray | memoryview,
        *,
        max_size: int | None = None,
    ) -> bytes:
        raw = bytes(data)
        if len(raw) < FRAME_SIZE:
            raise CompressionFrameError("Compressed payload is too short")

        _category, algorithm, original_size, flags, digest = _parse_frame(raw[:FRAME_SIZE])
        payload = raw[FRAME_SIZE:]
        limit = self.max_source_size if max_size is None else int(max_size)
        if original_size > limit:
            raise CompressionLimitError(f"Declared decompressed size exceeds limit {limit}")

        output = _decompress_bytes_payload(payload, algorithm)
        if len(output) != original_size:
            raise CompressionIntegrityError(
                f"Output size mismatch: expected {original_size}, got {len(output)}"
            )
        if _hash_bytes(output) != digest:
            raise CompressionIntegrityError("Checksum mismatch after decompression")
        return output

    async def analyze_bytes(
        self,
        data: bytes | bytearray | memoryview,
        *,
        filename_hint: str | None = None,
    ) -> CompressionScan:
        raw = bytes(data)
        profile = detect_profile_from_bytes(raw, filename_hint=filename_hint)
        return await asyncio.to_thread(
            scan_bytes,
            raw,
            profile,
            min_savings_percent=self.min_savings_percent,
        )
