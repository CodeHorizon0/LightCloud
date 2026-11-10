from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from anyio import CancelScope, create_task_group, sleep
from sqlalchemy import text
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.db.database import UserDatabase


class DatabaseCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = UserDatabase(Path(directory.name) / "main.db")
        await self.database.initialize()
        self.addAsyncCleanup(self.database.close)

    def assert_pool_idle(self) -> None:
        pool = self.database.engine.pool
        assert isinstance(pool, AsyncAdaptedQueuePool)
        self.assertEqual(pool.checkedout(), 0)

    async def test_cancelled_reads_leave_pool_reusable_without_errors(self) -> None:
        with self.assertNoLogs("sqlalchemy.pool", level="WARNING"):
            for phase in ["checkout", "query", "return"] * 8:
                with CancelScope() as scope:
                    if phase == "checkout":
                        scope.cancel()
                    async with self.database.sessions() as session:
                        if phase == "query":
                            scope.cancel()
                        await session.scalar(text("SELECT 1"))
                        if phase == "return":
                            scope.cancel()
                self.assertTrue(scope.cancelled_caught)
                await sleep(0)
                async with self.database.sessions() as session:
                    self.assertEqual(await session.scalar(text("SELECT 2")), 2)
        self.assert_pool_idle()

    async def test_cancelled_concurrent_readers_release_all_connections(self) -> None:
        async def reader() -> None:
            while True:
                async with self.database.sessions() as session:
                    await session.scalar(text("SELECT randomblob(32768)"))
                await sleep(0)

        with self.assertNoLogs("sqlalchemy.pool", level="WARNING"):
            for _ in range(8):
                async with create_task_group() as tasks:
                    for _ in range(6):
                        tasks.start_soon(reader)
                    await sleep(0.005)
                    tasks.cancel_scope.cancel()
                self.assert_pool_idle()
            async with self.database.sessions() as session:
                self.assertEqual(await session.scalar(text("PRAGMA quick_check")), "ok")

    async def test_cancelled_transaction_rolls_back_and_returns_connection(self) -> None:
        user = await self.database.create_user("Existing", "retained-hash")
        with self.assertRaises(asyncio.CancelledError):
            async with self.database.write_session() as session:
                await session.execute(
                    text("UPDATE users SET password_hash='uncommitted' WHERE id=:id"),
                    {"id": user.id.hex},
                )
                raise asyncio.CancelledError
        saved = await self.database.get_user("Existing")
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.password_hash, "retained-hash")
        self.assert_pool_idle()
