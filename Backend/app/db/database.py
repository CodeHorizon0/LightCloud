from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import select

from app.core.passwords import hash_password
from app.models import User

DB_PATH = "sqlite+aiosqlite:///./users.db"

engine = create_async_engine(DB_PATH, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(User.metadata.create_all)


async def create_user(username: str, password: str):
    username = username.strip()
    if not username:
        return None

    hash_pw = hash_password(password)

    async with SessionLocal() as session:
        user = User(username=username, password_hash=hash_pw)
        session.add(user)

        try:
            await session.commit()
            await session.refresh(user)
        except IntegrityError:
            await session.rollback()
            return None

        return {"id": user.id, "username": user.username}


async def get_user(username: str):
    username = username.strip()
    if not username:
        return None

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if user is None:
            return None

        return {
            "id": user.id,
            "username": user.username,
            "password_hash": user.password_hash,
        }


async def delete_user(username: str):
    username = username.strip()
    if not username:
        return False

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if user is None:
            return False

        await session.delete(user)
        await session.commit()
        return True