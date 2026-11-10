from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.database import UserDatabase
from app.db.sqlite import APPLICATION_ID, prepare_database, safe_wal_supported
from app.models import FileMetadata
from app.services.metadata import MetadataStore
from app.services.storage import UserStorageManager, clean_pending_blobs
from dbtool import backup_database, check_database


def entry(size: int = 10) -> FileMetadata:
    return {
        "stored_path": uuid4().hex,
        "stored_as_compressed": False,
        "compression_algorithm": "none",
        "original_size": size,
        "stored_size": size,
        "compression_percent": 0,
        "mime": "text/plain",
        "category": "text",
        "preview_profiled": True,
    }


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = UserDatabase(self.root / "main.db")
        await self.database.initialize()
        self.addAsyncCleanup(self.database.close)
        self.user = await self.database.create_user("Alice", "test-hash")
        self.store = MetadataStore(self.database, self.user.id)

    async def test_connection_reliability_and_indexed_lookups(self) -> None:
        async with self.database.engine.connect() as connection:
            for name, expected in {
                "foreign_keys": 1,
                "synchronous": 2,
                "busy_timeout": 15000,
                "trusted_schema": 0,
                "application_id": APPLICATION_ID,
            }.items():
                self.assertEqual(await connection.scalar(text(f"PRAGMA {name}")), expected)
            expected_mode = "wal" if safe_wal_supported(sqlite3.sqlite_version_info) else "delete"
            self.assertEqual(await connection.scalar(text("PRAGMA journal_mode")), expected_mode)
            for condition in [
                "user_id=:owner AND path='folder/code.py'",
                "user_id=:owner AND parent_path='folder' ORDER BY name",
                "user_id=:owner AND stored_path='blob'",
            ]:
                plan = await connection.execute(
                    text("EXPLAIN QUERY PLAN SELECT * FROM files WHERE " + condition),
                    {"owner": self.user.id.hex},
                )
                details = " ".join(str(row[-1]) for row in plan)
                self.assertIn("SEARCH files USING INDEX", details)
                self.assertNotIn("SCAN files", details)
            self.assertEqual(await connection.scalar(text("PRAGMA quick_check")), "ok")

    async def test_counters_transactions_and_foreign_key_cascade(self) -> None:
        async def state() -> tuple[int, int, int]:
            async with self.database.sessions() as session:
                row = (
                    await session.execute(
                        text("SELECT revision,file_count,quota_bytes FROM storage_state")
                    )
                ).one()
                return int(row[0]), int(row[1]), int(row[2])

        await self.store.commit({"a.py": entry(10), "folder/b.txt": entry(20)})
        self.assertEqual(await state(), (2, 2, 30))
        await self.store.commit({"a.py": entry(50)})
        self.assertEqual(await state(), (3, 2, 70))
        with self.assertRaises(IntegrityError):
            await self.store.commit({"valid.txt": entry(30), "invalid.txt": entry(-1)})
        self.assertIsNone(await self.store.get("valid.txt"))
        self.assertEqual(await state(), (3, 2, 70))
        await self.store.commit({}, ["folder/b.txt"])
        self.assertEqual(await state(), (4, 1, 50))
        await self.store.stage_blobs([uuid4().hex])
        await self.database.delete_user(self.user.id)
        async with self.database.sessions() as session:
            for table in ["files", "storage_state", "pending_blob_deletions"]:
                self.assertEqual(await session.scalar(text(f"SELECT COUNT(*) FROM {table}")), 0)
            self.assertIsNone((await session.execute(text("PRAGMA foreign_key_check"))).first())
        with self.assertRaises(IntegrityError):
            await self.store.commit({"orphan.txt": entry()})

    async def test_recovery_removes_uncommitted_blobs_and_preserves_live_files(self) -> None:
        manager = UserStorageManager(self.root / "storage", self.database)
        manager.initialize()
        storage = manager.for_user(self.user)
        storage.root_dir.mkdir()
        live = entry()
        unused = uuid4().hex
        for name in [live["stored_path"], unused]:
            (storage.root_dir / name).write_bytes(b"retained until recovery")
        await self.store.stage_blobs([live["stored_path"], unused])
        await self.store.commit({"code.py": live})
        # A stale cleanup item must never delete a referenced blob.
        await self.store.stage_blobs([live["stored_path"]])
        await manager.migrate_all()
        self.assertTrue((storage.root_dir / live["stored_path"]).exists())
        self.assertFalse((storage.root_dir / unused).exists())
        self.assertEqual(await self.store.pending_blobs(), [])
        self.assertFalse((storage.root_dir / "metadata.json").exists())
        with (
            self.assertLogs("app.services.storage", level="WARNING"),
            patch.object(
                storage.metadata_store, "pending_blobs", side_effect=OSError("temporary failure")
            ),
        ):
            await clean_pending_blobs(storage)
        self.assertIsNotNone(await self.store.get("code.py"))

    async def test_large_batches_keep_indexes_and_counters_consistent(self) -> None:
        metadata = {f"folder/{index}.py": entry(index + 1) for index in range(1200)}
        await self.store.commit(metadata)
        self.assertEqual(await self.store.load(list(metadata)), metadata)
        self.assertEqual(
            await self.store.referenced_blobs([item["stored_path"] for item in metadata.values()]),
            {item["stored_path"] for item in metadata.values()},
        )
        await self.store.commit({}, list(metadata))
        self.assertEqual(await self.store.load(), {})
        self.assertEqual(len(await self.store.pending_blobs()), 1200)
        await self.store.clear_pending(await self.store.pending_blobs())
        self.assertEqual(await self.store.pending_blobs(), [])
        async with self.database.sessions() as session:
            self.assertEqual(
                (
                    await session.execute(text("SELECT file_count,quota_bytes FROM storage_state"))
                ).one(),
                (0, 0),
            )

    async def test_backup_includes_committed_wal_and_is_independent(self) -> None:
        await self.store.commit({"saved.py": entry()})
        backup = self.root / "backup.db"
        await asyncio.to_thread(backup_database, self.database.path, backup)
        check_database(backup)
        await self.store.commit({}, ["saved.py"])
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(
                connection.execute("SELECT path FROM files").fetchall(), [("saved.py",)]
            )
        with self.assertRaises(ValueError):
            backup_database(self.database.path, backup)


class SQLiteMigrationTests(unittest.TestCase):
    def test_legacy_database_copy_includes_wal_and_keeps_original(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "users.db"
            with closing(sqlite3.connect(old)) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT)")
                connection.execute("INSERT INTO users VALUES ('id','Existing')")
                connection.commit()
                prepare_database(root / "main.db")
                with closing(sqlite3.connect(root / "main.db")) as migrated:
                    self.assertEqual(
                        migrated.execute("SELECT username FROM users").fetchall(), [("Existing",)]
                    )
                self.assertTrue((root / "users.db.migrated").exists())
                prepare_database(root / "main.db")

    def test_migration_preserves_previous_backup_and_adds_auth_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "users.db.migrated"
            archive.write_bytes(b"previous backup must remain unchanged")
            with closing(sqlite3.connect(root / "users.db")) as connection:
                connection.execute(
                    "CREATE TABLE users(id CHAR(32) PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO users VALUES (?, ?, ?)", (uuid4().hex, "Existing", "retained-hash")
                )
                connection.commit()

            async def migrate() -> None:
                database = UserDatabase(root / "main.db")
                try:
                    await database.initialize()
                    user = await database.get_user("Existing")
                    self.assertIsNotNone(user)
                    assert user is not None
                    self.assertEqual(user.password_hash, "retained-hash")
                    self.assertEqual(user.token_version, 1)
                    self.assertTrue(user.legacy_storage)
                finally:
                    await database.close()

            asyncio.run(migrate())
            self.assertEqual(archive.read_bytes(), b"previous backup must remain unchanged")
            self.assertEqual(len(list(root.glob("users.db.*.migrated"))), 1)

    def test_safe_fallback_for_unpatched_sqlite_and_future_schema_rejection(self) -> None:
        for version in [(3, 51, 3), (3, 53, 1), (3, 50, 7), (3, 44, 6)]:
            self.assertTrue(safe_wal_supported(version))
        for version in [(3, 51, 2), (3, 50, 6), (3, 44, 5), (3, 49, 0)]:
            self.assertFalse(safe_wal_supported(version))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "main.db"
            with patch("app.db.sqlite.safe_wal_supported", return_value=False):
                prepare_database(path)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone(), ("delete",))
                connection.execute("PRAGMA user_version=999")
            with self.assertRaisesRegex(RuntimeError, "Unsupported"):
                prepare_database(path)
