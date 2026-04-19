"""
Async SQLModel database engine + session factory.
"""
from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from config import settings


def _patch_sqlite_url(url: str) -> str:
    """Ensure SQLite URLs use the aiosqlite driver."""
    if url.startswith("sqlite:///") and "aiosqlite" not in url:
        return url.replace("sqlite:///", "sqlite+aiosqlite:///")
    return url


engine = create_async_engine(
    _patch_sqlite_url(settings.db_url),
    echo=settings.debug,
    connect_args={"check_same_thread": False} if "sqlite" in settings.db_url else {},
)

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=True,
)


async def init_db() -> None:
    """Create all tables + run lightweight migrations. Called once at app startup."""
    # Ensure data directory exists for SQLite
    if "sqlite" in settings.db_url:
        db_path = settings.db_url.split("///")[-1]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # Import models so SQLModel knows about them
    import db.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

        # ── Safe additive migrations ──────────────────────────────────────────
        # Add new columns that don't exist yet (idempotent — ignored if present)
        migrations = [
            "ALTER TABLE testrun ADD COLUMN test_code TEXT",
            "ALTER TABLE notification ADD COLUMN link TEXT",
        ]
        from sqlalchemy import text
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass  # Column already exists — safe to ignore


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a DB session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
