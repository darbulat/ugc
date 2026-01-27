"""Database session factory and transaction helpers."""

from contextlib import asynccontextmanager
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_db_engine(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
) -> Engine:
    """Create a SQLAlchemy engine."""

    url = make_url(database_url)
    if url.drivername.startswith("sqlite"):
        return create_engine(database_url, pool_pre_ping=True)
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
    )


def _ensure_async_url(url: URL) -> URL:
    if url.drivername.startswith("sqlite"):
        if "+aiosqlite" in url.drivername:
            return url
        return url.set(drivername="sqlite+aiosqlite")
    if "+psycopg" in url.drivername or "+asyncpg" in url.drivername:
        return url
    if url.drivername.startswith("postgresql"):
        return url.set(drivername="postgresql+psycopg")
    return url


def create_async_db_engine(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
) -> AsyncEngine:
    """Create a configured session factory."""

    url = _ensure_async_url(make_url(database_url))
    if url.drivername.startswith("sqlite"):
        return create_async_engine(str(url), pool_pre_ping=True)
    return create_async_engine(
        str(url),
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
    )


def create_session_factory(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
) -> async_sessionmaker[AsyncSession]:
    """Create a configured async session factory."""

    engine = create_async_db_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
    )
    return async_sessionmaker(bind=engine, expire_on_commit=False)


class SessionTransactionManager:
    """Transaction manager for Async SQLAlchemy sessions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def transaction(self):
        """Provide a transactional session scope."""
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
