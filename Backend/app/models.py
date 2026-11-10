from __future__ import annotations

from typing import NotRequired, TypedDict
from uuid import UUID, uuid4

from pydantic import BaseModel, field_validator
from pydantic import Field as PydanticField
from sqlalchemy import CheckConstraint, Index
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
    preview_profiled: NotRequired[bool]


class DeleteFilesRequest(BaseModel):
    filenames: list[str] = PydanticField(min_length=1, max_length=1000)


class SyncDeleteRequest(DeleteFilesRequest):
    revisions: dict[str, str | None] = PydanticField(max_length=1000)


class Credentials(BaseModel):
    username: str = PydanticField(min_length=1, max_length=32)
    password: str = PydanticField(min_length=8, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("username", "password")
    @classmethod
    def validate_encoding(cls, value: str) -> str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("Invalid Unicode") from exc
        return value


class Registration(Credentials):
    username: str = PydanticField(min_length=3, max_length=32)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    username: str = Field(index=True, unique=True, nullable=False, max_length=32)
    password_hash: str = Field(nullable=False, max_length=255)
    token_version: int = Field(default=1, nullable=False)
    legacy_storage: bool = Field(default=False, nullable=False)


class PasswordChange(BaseModel):
    current_password: str = PydanticField(min_length=1, max_length=128)
    new_password: str = PydanticField(min_length=8, max_length=128)

    @field_validator("current_password", "new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        value.encode("utf-8")
        return value


class FileRecord(SQLModel, table=True):
    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint("original_size >= 0 AND stored_size >= 0"),
        Index("ix_files_owner_folder_name", "user_id", "parent_path", "name"),
        Index("ix_files_owner_blob", "user_id", "stored_path"),
    )
    user_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE", primary_key=True)
    path: str = Field(primary_key=True, max_length=4096)
    parent_path: str = Field(max_length=4096)
    name: str = Field(max_length=255)
    stored_path: str
    stored_as_compressed: bool
    compression_algorithm: str
    original_size: int
    stored_size: int
    compression_percent: float
    mime: str
    category: str
    preview_profiled: bool = False
    modified_at: int


class StorageState(SQLModel, table=True):
    __tablename__ = "storage_state"
    __table_args__ = (CheckConstraint("revision >= 0 AND file_count >= 0 AND quota_bytes >= 0"),)
    user_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE", primary_key=True)
    revision: int = 0
    file_count: int = 0
    quota_bytes: int = 0
    legacy_imported: bool = False


class PendingBlob(SQLModel, table=True):
    __tablename__ = "pending_blob_deletions"
    user_id: UUID = Field(foreign_key="users.id", ondelete="CASCADE", primary_key=True)
    stored_path: str = Field(primary_key=True)


class RevokedSession(SQLModel, table=True):
    __tablename__ = "revoked_sessions"

    id: UUID = Field(primary_key=True)
    expires_at: int = Field(index=True)
    user_id: UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="CASCADE", index=True
    )
