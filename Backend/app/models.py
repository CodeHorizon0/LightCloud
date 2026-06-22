from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict
from uuid import UUID, uuid4

import asyncio
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Field, SQLModel


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


# Metadata model
@dataclass(slots=True)
class MetadataJob:
    filename: str
    tmp_path: Path
    compressed_path: Path
    final_path: Path
    future: asyncio.Future[UploadResult]


class UserCreate(BaseModel):
    username: str = PydanticField(min_length=3, max_length=32)
    password: str = PydanticField(min_length=8, max_length=128)

class UserOut(BaseModel):
    id: UUID
    username: str


# User account table
class UserLogin(BaseModel):
    username: str = PydanticField(min_length=3, max_length=32)
    password: str = PydanticField(min_length=8, max_length=128)

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
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
