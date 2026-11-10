from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from time import time_ns
from typing import Protocol, cast

from sqlalchemy import Connection

APPLICATION_ID = 0x4C434442
SCHEMA_VERSION = 1


class Cursor(Protocol):
    def execute(self, statement: str) -> object: ...
    def close(self) -> None: ...


class SQLiteConnection(Protocol):
    isolation_level: str | None

    def cursor(self) -> Cursor: ...


def configure_connection(connection: object, record: object) -> None:
    db = cast(SQLiteConnection, connection)
    db.isolation_level = None
    cursor = db.cursor()
    try:
        for statement in (
            "PRAGMA foreign_keys=ON",
            "PRAGMA busy_timeout=15000",
            "PRAGMA synchronous=FULL",
            "PRAGMA fullfsync=ON",
            "PRAGMA checkpoint_fullfsync=ON",
            "PRAGMA trusted_schema=OFF",
            "PRAGMA secure_delete=ON",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA cache_size=-8192",
            "PRAGMA wal_autocheckpoint=1000",
            "PRAGMA journal_size_limit=67108864",
        ):
            cursor.execute(statement)
    finally:
        cursor.close()


def begin_transaction(connection: Connection) -> None:
    mode = (
        "BEGIN IMMEDIATE"
        if connection.get_execution_options().get("write_transaction")
        else "BEGIN"
    )
    connection.exec_driver_sql(mode)


def fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def safe_wal_supported(version: tuple[int, ...]) -> bool:
    return (
        version >= (3, 51, 3) or (3, 50, 7) <= version < (3, 51) or (3, 44, 6) <= version < (3, 45)
    )


def prepare_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = path.with_name("users.db")
    if path.name == "main.db" and not path.exists() and legacy.exists():
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".main-migration-", suffix=".db")
        os.close(fd)
        target = Path(temporary)
        try:
            with (
                closing(sqlite3.connect(legacy)) as source,
                closing(sqlite3.connect(target)) as destination,
            ):
                source.backup(destination)
                if destination.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise RuntimeError("Legacy database integrity check failed")
            with target.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(target, path)
            archive = legacy.with_suffix(".db.migrated")
            if archive.exists():
                archive = legacy.with_name(f"users.db.{time_ns()}.migrated")
            legacy.rename(archive)
            fsync_directory(path.parent)
        finally:
            target.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)
    with closing(sqlite3.connect(path, timeout=15)) as connection:
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise RuntimeError("Database integrity check failed")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        application = connection.execute("PRAGMA application_id").fetchone()[0]
        if version > SCHEMA_VERSION or application not in {0, APPLICATION_ID}:
            raise RuntimeError("Unsupported database format")
        mode = "wal" if safe_wal_supported(sqlite3.sqlite_version_info) else "delete"
        if connection.execute(f"PRAGMA journal_mode={mode}").fetchone()[0] != mode:
            raise RuntimeError("Could not enable SQLite journaling")
