from __future__ import annotations

import bz2
import math
import lzma
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .detection import FileProfile

COPY_ONLY_CATEGORIES = {"video", "archive"}
LOSSY_IMAGE_MIMES = {"image/jpeg", "image/jpg", "image/webp", "image/avif"}
LOSSY_AUDIO_MIMES = {"audio/mpeg", "audio/aac", "audio/ogg", "audio/opus", "audio/mp4", "audio/x-ms-wma"}

def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    value = 0.0
    for count in counts.values():
        p = count / total
        value -= p * math.log2(p)
    return value

def _unique_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    return len(set(data)) / 256.0

def _zero_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    return data.count(0) / len(data)

def _transition_density(data: bytes) -> float:
    if len(data) < 2:
        return 0.0
    transitions = 0
    prev = data[0]
    for byte in data[1:]:
        if byte != prev:
            transitions += 1
        prev = byte
    return transitions / (len(data) - 1)

def _compress_ratio(sample: bytes, algo: str) -> float:
    if not sample:
        return 1.0

    if algo == "copy":
        return 1.0
    if algo == "zlib":
        compressed = zlib.compress(sample, level=6)
    elif algo == "lzma":
        compressed = lzma.compress(sample, preset=6, check=lzma.CHECK_NONE)
    elif algo == "bz2":
        compressed = bz2.compress(sample)
    else:
        raise ValueError(f"Unknown algorithm: {algo}")
    return len(compressed) / len(sample)

def _allowed_algorithms(profile: FileProfile) -> tuple[str, ...]:
    if profile.category in COPY_ONLY_CATEGORIES:
        return ("copy",)
    if profile.category == "image":
        if profile.mime in LOSSY_IMAGE_MIMES:
            return ("copy",)
        return ("zlib", "lzma", "copy")
    if profile.category == "audio":
        if profile.mime in LOSSY_AUDIO_MIMES:
            return ("copy",)
        return ("zlib", "lzma", "bz2", "copy")
    if profile.category == "executable":
        return ("lzma", "zlib", "copy")
    if profile.category == "text":
        return ("zlib", "lzma", "bz2", "copy")
    return ("zlib", "lzma", "bz2", "copy")

def _sample_bytes_from_file(path: Path, sample_size: int, windows: int = 4) -> bytes:
    size = path.stat().st_size
    if size <= 0:
        return b""
    if size <= sample_size:
        with path.open("rb") as fh:
            return fh.read(sample_size)

    windows = max(1, windows)
    block = max(4096, sample_size // windows)
    positions: list[int] = []
    if windows == 1:
        positions = [0]
    else:
        step = max(1, (size - block) // max(1, windows - 1))
        positions = [min(i * step, max(0, size - block)) for i in range(windows)]

    chunks: list[bytes] = []
    total = 0
    with path.open("rb") as fh:
        for pos in positions:
            fh.seek(pos)
            chunk = fh.read(block)
            if not chunk:
                continue
            chunks.append(chunk)
            total += len(chunk)
            if total >= sample_size:
                break
    return b"".join(chunks)[:sample_size]

def _scan_sample(sample: bytes, profile: FileProfile, min_savings_percent: float, size: int) -> "CompressionScan":
    entropy = _entropy(sample)
    unique_ratio = _unique_ratio(sample)
    zero_ratio = _zero_ratio(sample)
    transition_density = _transition_density(sample)

    allowed = _allowed_algorithms(profile)
    candidate_ratios: dict[str, float] = {}
    for algo in allowed:
        candidate_ratios[algo] = _compress_ratio(sample, algo)

    if not candidate_ratios:
        candidate_ratios = {"copy": 1.0}

    recommended_algorithm = min(
        candidate_ratios.items(),
        key=lambda item: (item[1], 0 if item[0] == "zlib" else 1),
    )[0]
    estimated_ratio = candidate_ratios[recommended_algorithm]
    estimated_savings_percent = max(0.0, round((1.0 - estimated_ratio) * 100.0, 2))

    if profile.category in COPY_ONLY_CATEGORIES:
        should_compress = False
        reason = f"{profile.category} is treated as copy-only"
        recommended_algorithm = "copy"
        estimated_ratio = 1.0
        estimated_savings_percent = 0.0
    elif profile.category == "image" and profile.mime in LOSSY_IMAGE_MIMES:
        should_compress = False
        reason = f"{profile.mime} is already compressed"
        recommended_algorithm = "copy"
        estimated_ratio = 1.0
        estimated_savings_percent = 0.0
    elif profile.category == "audio" and profile.mime in LOSSY_AUDIO_MIMES:
        should_compress = False
        reason = f"{profile.mime} is already compressed"
        recommended_algorithm = "copy"
        estimated_ratio = 1.0
        estimated_savings_percent = 0.0
    elif size <= 0:
        should_compress = False
        reason = "empty file"
        recommended_algorithm = "copy"
        estimated_ratio = 1.0
        estimated_savings_percent = 0.0
    else:
        entropy_bias = max(0.0, 1.0 - entropy / 8.0)
        structure_bias = max(0.0, 1.0 - transition_density)
        predicted_strength = (entropy_bias * 0.55) + (structure_bias * 0.25) + ((1.0 - unique_ratio) * 0.20)
        should_compress = estimated_savings_percent >= min_savings_percent and predicted_strength >= 0.15
        if should_compress:
            reason = f"estimated savings {estimated_savings_percent:.2f}% with {recommended_algorithm}"
        else:
            reason = f"estimated savings {estimated_savings_percent:.2f}% is below threshold"

    return CompressionScan(
        path=profile.name or "",
        size=size,
        mime=profile.mime,
        category=profile.category,
        entropy=round(entropy, 4),
        unique_ratio=round(unique_ratio, 4),
        zero_ratio=round(zero_ratio, 4),
        transition_density=round(transition_density, 4),
        sample_size=len(sample),
        candidate_ratios={k: round(v, 4) for k, v in candidate_ratios.items()},
        recommended_algorithm=recommended_algorithm,
        estimated_ratio=round(estimated_ratio, 4),
        estimated_savings_percent=estimated_savings_percent,
        should_compress=should_compress,
        reason=reason,
    )

@dataclass(slots=True, frozen=True)
class CompressionScan:
    path: str
    size: int
    mime: str
    category: str
    entropy: float
    unique_ratio: float
    zero_ratio: float
    transition_density: float
    sample_size: int
    candidate_ratios: dict[str, float] = field(default_factory=dict)
    recommended_algorithm: str = "copy"
    estimated_ratio: float = 1.0
    estimated_savings_percent: float = 0.0
    should_compress: bool = False
    reason: str = ""

def scan_bytes(
    data: bytes,
    profile: FileProfile,
    *,
    min_savings_percent: float,
) -> CompressionScan:
    sample = data[: max(1, min(len(data), 1024 * 1024))]
    return _scan_sample(sample, profile, min_savings_percent, len(data))

def scan_file(
    path: Path,
    profile: FileProfile,
    *,
    sample_size: int,
    min_savings_percent: float,
) -> CompressionScan:
    sample = _sample_bytes_from_file(path, sample_size=sample_size)
    return _scan_sample(sample, profile, min_savings_percent, path.stat().st_size)
