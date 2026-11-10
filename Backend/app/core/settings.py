from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = BASE_DIR / "config.json"
MIB = 1024 * 1024
DEFAULT_SECRET = "CHANGE_THIS_SECRET_TO_SOMETHING_STRONG"


class CorsSettings(BaseModel):
    allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    allow_methods: list[str] = Field(default_factory=lambda: ["*"])
    allow_headers: list[str] = Field(default_factory=lambda: ["*"])
    allow_credentials: bool = True

    @field_validator("allow_origins")
    @classmethod
    def explicit_origins(cls, values: list[str]) -> list[str]:
        if "*" in values or "null" in values:
            raise ValueError("List explicit trusted frontend origins")
        return values


class CompressionSettings(BaseModel):
    scan_sample_size: int = Field(default=MIB, ge=4096, le=4 * MIB)
    min_savings_percent: float = Field(default=3.0, ge=0, le=100)
    max_source_size: int = Field(default=2 * 1024 * MIB, ge=1)


class UploadSettings(BaseModel):
    chunk_size: int = Field(default=2 * MIB, ge=64 * 1024, le=8 * MIB)


class Settings(BaseModel):
    storage_dir: Path = Path("storage/files")
    database_file: Path = Path("main.db")
    host: str = "127.0.0.1"
    port: int = Field(default=3000, ge=1, le=65535)
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    cors: CorsSettings = Field(default_factory=CorsSettings)
    compression: CompressionSettings = Field(default_factory=CompressionSettings)
    upload_worker: UploadSettings = Field(default_factory=UploadSettings)
    compression_level: int = Field(default=6, ge=1, le=9)
    jwt_secret: str = Field(default="", repr=False)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS512"
    max_file_size_mb: int = Field(default=2000, ge=1)
    max_batch_size_mb: int | None = Field(default=None, ge=1)
    max_upload_files: int = Field(default=10, ge=1, le=100)
    max_filename_depth: int = Field(default=10, ge=1, le=32)
    concurrent_uploads: int = Field(default=2, ge=1, le=16)
    user_quota_mb: int = Field(default=20 * 1024, ge=1)
    user_file_limit: int = Field(default=10000, ge=1)
    cookie_secure: bool = False
    access_token_expire_minutes: int = Field(default=60, ge=1, le=10080)

    @field_validator("database_file")
    @classmethod
    def main_database_name(cls, value: Path) -> Path:
        return value.with_name("main.db") if value.name == "users.db" else value

    @property
    def max_file_size(self) -> int:
        return self.max_file_size_mb * MIB

    @property
    def max_batch_size(self) -> int:
        return (self.max_batch_size_mb or self.max_file_size_mb) * MIB


def load_settings(config_path: Path = CONFIG_PATH) -> Settings:
    settings = Settings.model_validate_json(config_path.read_text(encoding="utf-8"))
    settings.storage_dir = (config_path.parent / settings.storage_dir).resolve()
    if "database_file" in settings.model_fields_set:
        settings.database_file = (config_path.parent / settings.database_file).resolve()
    else:
        old_path = Path.cwd() / "users.db"
        settings.database_file = (
            Path.cwd() if old_path.is_file() else config_path.parent
        ) / "main.db"
    settings.jwt_secret = os.environ.get("LIGHTCLOUD_JWT_SECRET", settings.jwt_secret)
    if settings.jwt_secret == DEFAULT_SECRET:
        settings.jwt_secret = ""
    if settings.jwt_secret and len(settings.jwt_secret.encode("utf-8")) < 32:
        raise ValueError("JWT secret must contain at least 32 bytes")
    return settings
