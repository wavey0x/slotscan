"""Database connection and session management."""

from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings, sqlite_database_url


def create_database_engine(database_path: Path) -> AsyncEngine:
    """Create the SQLite engine used by the application and integration tests."""
    database_engine = create_async_engine(
        sqlite_database_url(database_path),
        connect_args={"timeout": 5.0},
        echo=False,
    )

    @event.listens_for(database_engine.sync_engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return database_engine


settings = get_settings()
engine = create_database_engine(settings.database_path)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for dependency injection."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
