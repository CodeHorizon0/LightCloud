from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict, List
from uuid import UUID, uuid4

import asyncio
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Field, SQLModel, Relationship


class FileMetadata(TypedDict):
    stored_path: str
    stored_as_compressed: bool
    compression_algorithm: str
    original_size: int
    stored_size: int
    compression_percent: float
    mime: str
    category: str


class UploadResult(TypedDict):
    filename: str
    message: str


class DeleteFilesRequest(BaseModel):
    filenames: list[str] = PydanticField(min_length=1)


# Metadata job
@dataclass(slots=True)
class MetadataJob:
    filename: str
    tmp_path: Path
    compressed_path: Path
    final_path: Path
    future: asyncio.Future[UploadResult]


# Pydantic models for users
class UserCreate(BaseModel):
    username: str = PydanticField(min_length=3, max_length=32)
    password: str = PydanticField(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: UUID
    username: str


class UserLogin(BaseModel):
    username: str = PydanticField(min_length=3, max_length=32)
    password: str = PydanticField(min_length=8, max_length=128)


# SQLModel tables
class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        nullable=False,
        index=True,
        unique=True,
    )
    username: str = Field(
        index=True,
        unique=True,
        nullable=False,
        min_length=3,
        max_length=32,
    )
    password_hash: str = Field(
        nullable=False,
        max_length=255,
    )

    # Uncommented in future versions
    # # Storage size
    # storage_quota_gb: int = Field(default=10)
    # storage_used_gb: int = Field(default=0)

    # # Profile
    # display_name: str | None = Field(default=None, max_length=50)
    # avatar_url: str | None = Field(default=None, max_length=500)
    # locale: str = Field(default="en", nullable=False, max_length=20)

    # # Time data
    # created_at: datetime = Field(
    #     default_factory=lambda: datetime.now(timezone.utc),
    #     nullable=False,
    #     index=True,
    # )
    # last_login_at: datetime | None = Field(default=None, index=True)

    # Однонаправленная связь: из User можно получить все его файлы
#     files: List["File"] = Relationship()

# class File(SQLModel, table=True):
#     __tablename__ = "files"

#     id: UUID = Field(
#         default_factory=uuid4,
#         primary_key=True,
#         nullable=False,
#         index=True,
#         unique=True,
#     )
#     user_id: UUID = Field(
#         foreign_key="users.id",
#         nullable=False,
#         index=True,
#     )
#     filename: str = Field(
#         nullable=False,
#         max_length=255,
#     )
#     stored_path: str = Field(
#         nullable=False,
#         max_length=500,
#     )
#     stored_as_compressed: bool = Field(
#         default=False,
#     )
#     compression_algorithm: str = Field(
#         default="none",
#         max_length=50,
#     )
#     original_size: int = Field(
#         default=0,
#     )
#     stored_size: int = Field(
#         default=0,
#     )
#     compression_percent: float = Field(
#         default=0.0,
#     )
#     mime: str = Field(
#         default="application/octet-stream",
#         max_length=100,
#     )
#     category: str = Field(
#         default="other",
#         max_length=50,
#     )
#     created_at: datetime = Field(
#         default_factory=lambda: datetime.now(timezone.utc),
#         nullable=False,
#         index=True,
#     )
