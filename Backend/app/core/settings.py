# app/core/settings.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config.json"


@dataclass(slots=True, frozen=True)
class Settings:
    project_root: Path
    storage_dir: Path
    meta_file: Path
    compression_level: int
    chunk_size: int
    cache_duration: int
    host: str
    port: int
    cors_allow_origins: list[str]
    cors_allow_methods: list[str]
    cors_allow_headers: list[str]
    gzip_minimum_size: int
    compression_scan_sample_size: int
    compression_min_savings_percent: float
    compression_max_source_size: int
    jwt_secret: str
    jwt_algorithm: str            
    max_file_size: int           
    max_upload_files: int
    max_filename_depth: int
    cookie_secure: bool
    access_token_expire_minutes: int
    idle_threshold_seconds: int = 300  
    idle_check_interval_seconds: int = 60


def _get_nested(data: dict[str, Any], *keys: str, default: Any) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return default if current is None else current


def load_settings(config_path: Path = CONFIG_PATH) -> Settings:
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)

    storage_dir = BASE_DIR / config.get("storage_dir", "storage/files")
    meta_file = BASE_DIR / config.get("metadata_file", "storage/metadata.json")

    storage_dir.mkdir(parents=True, exist_ok=True)

    max_file_size_mb = int(config.get("max_file_size_mb", 100))
    max_file_size = max_file_size_mb * 1024 * 1024
    max_upload_files = int(config.get("max_upload_files", 10))
    max_filename_depth = int(config.get("max_filename_depth", 10))

    jwt_secret = config.get("jwt_secret", "CHANGE_THIS_SECRET_TO_SOMETHING_STRONG")
    jwt_algorithm = config.get("jwt_algorithm", "HS256")   # <-- чтение алгоритма
    cookie_secure = bool(config.get("cookie_secure", False))
    access_token_expire_minutes = int(config.get("access_token_expire_minutes", 60))

    return Settings(
        project_root=BASE_DIR,
        storage_dir=storage_dir,
        meta_file=meta_file,
        compression_level=int(config.get("compression_level", 9)),
        chunk_size=int(_get_nested(config, "upload_worker", "chunk_size", default=1048576)),
        cache_duration=int(_get_nested(config, "cache", "cache_duration_seconds", default=300)),
        host=str(config.get("host", "0.0.0.0")),
        port=int(config.get("port", 3000)),
        cors_allow_origins=list(_get_nested(config, "cors", "allow_origins", default=["*"])),
        cors_allow_methods=list(_get_nested(config, "cors", "allow_methods", default=["*"])),
        cors_allow_headers=list(_get_nested(config, "cors", "allow_headers", default=["*"])),
        gzip_minimum_size=int(_get_nested(config, "gzip", "minimum_size", default=500)),
        compression_scan_sample_size=int(
            _get_nested(config, "compression", "scan_sample_size", default=1024 * 1024)
        ),
        compression_min_savings_percent=float(
            _get_nested(config, "compression", "min_savings_percent", default=3.0)
        ),
        compression_max_source_size=int(
            _get_nested(config, "compression", "max_source_size", default=2 * 1024 * 1024 * 1024)
        ),
        jwt_secret=jwt_secret,
        jwt_algorithm=jwt_algorithm,          
        max_file_size=max_file_size,
        max_upload_files=max_upload_files,
        max_filename_depth=max_filename_depth,
        cookie_secure=cookie_secure,
        access_token_expire_minutes=access_token_expire_minutes,
    )