from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from time import time
from uuid import UUID

from anyio import CancelScope, to_thread
from anyio.lowlevel import checkpoint_if_cancelled
from sqlalchemy import URL, delete, event, literal, text, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, col, select

from app.core.auth_helper import AccessToken
from app.db.sqlite import (
    APPLICATION_ID,
    SCHEMA_VERSION,
    begin_transaction,
    configure_connection,
    prepare_database,
)
from app.models import PendingBlob, RevokedSession, StorageState, User
from app.services.file_lock import AsyncFileLock

logger = logging.getLogger(__name__)

TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS files_identity_immutable BEFORE UPDATE ON files
    WHEN OLD.user_id != NEW.user_id OR OLD.path != NEW.path BEGIN
    SELECT RAISE(ABORT,'File identity cannot change in place'); END""",
    """CREATE TRIGGER IF NOT EXISTS files_insert_state AFTER INSERT ON files BEGIN
    INSERT OR IGNORE INTO storage_state(user_id,revision,file_count,quota_bytes,legacy_imported) VALUES(NEW.user_id,0,0,0,0);
    UPDATE storage_state SET revision=revision+1, file_count=file_count+1,
    quota_bytes=quota_bytes+MAX(NEW.original_size,NEW.stored_size) WHERE user_id=NEW.user_id;
    END""",
    """CREATE TRIGGER IF NOT EXISTS files_delete_state AFTER DELETE ON files BEGIN
    UPDATE storage_state SET revision=revision+1, file_count=file_count-1,
    quota_bytes=quota_bytes-MAX(OLD.original_size,OLD.stored_size) WHERE user_id=OLD.user_id;
    END""",
    """CREATE TRIGGER IF NOT EXISTS files_update_state AFTER UPDATE ON files BEGIN
    UPDATE storage_state SET revision=revision+1,
    quota_bytes=quota_bytes-MAX(OLD.original_size,OLD.stored_size)+MAX(NEW.original_size,NEW.stored_size)
    WHERE user_id=NEW.user_id;
    END""",
)


class UserAlreadyExistsError(Exception):
    pass


class UserDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.engine = create_async_engine(
            URL.create("sqlite+aiosqlite", database=str(path)),
            connect_args={"timeout": 15},
            pool_size=5,
            max_overflow=5,
        )
        event.listen(self.engine.sync_engine, "connect", configure_connection)
        event.listen(self.engine.sync_engine, "begin", begin_transaction)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def sessions(self) -> AsyncIterator[AsyncSession]:
        await checkpoint_if_cancelled()
        # SQLite operations and connection return form one bounded unit.
        with CancelScope(shield=True):
            async with self._sessions() as session:
                yield session
        await checkpoint_if_cancelled()

    @asynccontextmanager
    async def write_session(self) -> AsyncIterator[AsyncSession]:
        await checkpoint_if_cancelled()
        with CancelScope(shield=True):
            async with self.engine.connect() as connection:
                await connection.execution_options(write_transaction=True)
                async with (
                    connection.begin(),
                    AsyncSession(bind=connection, expire_on_commit=False) as session,
                ):
                    yield session
                    await session.flush()
        await checkpoint_if_cancelled()

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with AsyncFileLock(self.path.with_name(f".{self.path.name}.migration.lock")):
            await to_thread.run_sync(prepare_database, self.path)
            async with self.engine.connect() as conn:
                await conn.execution_options(write_transaction=True)
                async with conn.begin():
                    await conn.run_sync(SQLModel.metadata.create_all)
                    columns = {
                        row.name
                        for row in (await conn.execute(text("PRAGMA table_info(users)"))).all()
                    }
                    if "token_version" not in columns:
                        await conn.execute(
                            text(
                                "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1"
                            )
                        )
                    if "legacy_storage" not in columns:
                        await conn.execute(
                            text(
                                "ALTER TABLE users ADD COLUMN legacy_storage BOOLEAN NOT NULL DEFAULT 1"
                            )
                        )
                    for column in ("display_name", "bio", "profile_revision"):
                        if column in columns:
                            await conn.execute(text(f'ALTER TABLE users DROP COLUMN "{column}"'))
                    revoked = {
                        row.name
                        for row in (
                            await conn.execute(text("PRAGMA table_info(revoked_sessions)"))
                        ).all()
                    }
                    if "user_id" not in revoked:
                        await conn.execute(
                            text(
                                "ALTER TABLE revoked_sessions ADD COLUMN user_id CHAR(32) REFERENCES users(id) ON DELETE CASCADE"
                            )
                        )
                        await conn.execute(
                            text(
                                "CREATE INDEX IF NOT EXISTS ix_revoked_sessions_user_id ON revoked_sessions(user_id)"
                            )
                        )
                    await conn.execute(
                        text(
                            "INSERT OR IGNORE INTO storage_state(user_id,revision,file_count,quota_bytes,legacy_imported) SELECT id,0,0,0,0 FROM users"
                        )
                    )
                    for trigger in TRIGGERS:
                        await conn.execute(text(trigger))
                    await conn.execute(text(f"PRAGMA application_id={APPLICATION_ID}"))
                    await conn.execute(text(f"PRAGMA user_version={SCHEMA_VERSION}"))
                    if (await conn.execute(text("PRAGMA foreign_key_check"))).first() is not None:
                        raise RuntimeError("Database foreign key check failed")
                    await conn.execute(text("PRAGMA optimize"))

    async def close(self) -> None:
        with CancelScope(shield=True):
            try:
                async with self.engine.connect() as conn:
                    await conn.execute(text("PRAGMA optimize"))
            except SQLAlchemyError:
                logger.warning("Could not optimize database on shutdown", exc_info=True)
            finally:
                await self.engine.dispose()

    async def create_user(self, username: str, password_hash: str) -> User:
        user = User(username=username, password_hash=password_hash)
        try:
            async with self.write_session() as session:
                session.add(user)
                await session.flush()
                session.add(StorageState(user_id=user.id, legacy_imported=True))
        except IntegrityError as exc:
            raise UserAlreadyExistsError from exc
        return user

    async def get_user(self, username: str) -> User | None:
        async with self.sessions() as session:
            return await session.scalar(select(User).where(User.username == username))

    async def get_session_user(self, token: AccessToken) -> User | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(User)
                .where(User.id == token.user_id)
                .where(
                    ~select(RevokedSession.id).where(RevokedSession.id == token.session_id).exists()
                )
            )

    async def storage_maintenance_users(self) -> list[User]:
        async with self.sessions() as session:
            return list(
                await session.scalars(
                    select(User)
                    .join(StorageState, col(StorageState.user_id) == col(User.id))
                    .where(
                        ~col(StorageState.legacy_imported)
                        | select(PendingBlob.user_id)
                        .where(col(PendingBlob.user_id) == col(User.id))
                        .exists()
                    )
                )
            )

    async def legacy_usernames(self) -> list[str]:
        async with self.sessions() as session:
            return list(await session.scalars(select(User.username).where(User.legacy_storage)))

    async def revoke_session(self, token: AccessToken) -> None:
        async with self.write_session() as session:
            await session.execute(
                delete(RevokedSession).where(col(RevokedSession.expires_at) <= int(time()))
            )
            values = select(
                literal(token.session_id), literal(token.expires_at), col(User.id)
            ).where(col(User.id) == token.user_id)
            await session.execute(
                insert(RevokedSession)
                .from_select(["id", "expires_at", "user_id"], values)
                .on_conflict_do_nothing()
            )

    async def revoke_all(self, token: AccessToken) -> None:
        async with self.write_session() as session:
            await session.execute(
                update(User)
                .where(col(User.id) == token.user_id, col(User.token_version) == token.version)
                .values(token_version=User.token_version + 1)
            )

    async def change_password(self, token: AccessToken, old_hash: str, new_hash: str) -> bool:
        async with self.write_session() as session:
            changed = await session.scalar(
                update(User)
                .where(
                    col(User.id) == token.user_id,
                    col(User.token_version) == token.version,
                    col(User.password_hash) == old_hash,
                    ~select(RevokedSession.id)
                    .where(RevokedSession.id == token.session_id)
                    .exists(),
                )
                .values(password_hash=new_hash, token_version=User.token_version + 1)
                .returning(col(User.id))
            )
            return changed is not None

    async def delete_user(self, user_id: UUID) -> None:
        async with self.write_session() as session:
            await session.execute(delete(User).where(col(User.id) == user_id))
