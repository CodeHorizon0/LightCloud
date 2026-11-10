from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from app.db.sqlite import APPLICATION_ID, SCHEMA_VERSION, fsync_directory


def check_database(path: Path) -> None:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RuntimeError("SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("SQLite foreign key check failed")
        if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            raise RuntimeError("This is not a LightCloud database")
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise RuntimeError("Unsupported LightCloud database version")


def backup_database(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve() or target.exists():
        raise ValueError("Backup destination must be a new file")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".backup-", suffix=".db", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with (
            closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original,
            closing(sqlite3.connect(temporary)) as destination,
        ):
            original.backup(destination, pages=256)
        check_database(temporary)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        # A concurrent backup must not overwrite an existing destination.
        os.link(temporary, target)
        fsync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check or back up a LightCloud SQLite database.")
    parser.add_argument("action", choices=["check", "backup"])
    parser.add_argument("database", type=Path)
    parser.add_argument("destination", type=Path, nargs="?")
    args = parser.parse_args()
    if args.action == "backup":
        if args.destination is None:
            parser.error("backup requires a destination")
        backup_database(args.database, args.destination)
        print(f"Backup created: {args.destination}")
    else:
        check_database(args.database)
        print("Database integrity and foreign keys: OK")


if __name__ == "__main__":
    main()
