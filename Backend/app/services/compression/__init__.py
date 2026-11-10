from .detection import FileProfile, detect_profile_from_bytes, detect_profile_from_path
from .manager import (
    CompressionError,
    CompressionFrameError,
    CompressionIntegrityError,
    CompressionLimitError,
    CompressionManager,
    CompressionResult,
)

__all__ = [
    "FileProfile",
    "detect_profile_from_bytes",
    "detect_profile_from_path",
    "CompressionError",
    "CompressionFrameError",
    "CompressionIntegrityError",
    "CompressionLimitError",
    "CompressionManager",
    "CompressionResult",
]
