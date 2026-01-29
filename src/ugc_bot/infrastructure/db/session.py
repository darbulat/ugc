"""Database session factory and transaction helpers."""

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol, TypeVar

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
        return create_async_engine(url, pool_pre_ping=True)
    return create_async_engine(
        url,
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


T = TypeVar("T")


class TransactionManagerProtocol(Protocol):
    """Protocol for transaction manager with .transaction() context manager."""

    def transaction(self) -> Any:
        """Return async context manager yielding session."""


async def with_optional_tx(
    transaction_manager: TransactionManagerProtocol | None,
    fn: Callable[[object | None], Awaitable[T]],
) -> T:
    """Run an async function with optional transaction/session.

    If transaction_manager is not None, opens a transaction and calls fn(session).
    Otherwise calls fn(None). Use this to avoid duplicating "if tm is None / else
    async with tm.transaction()" branches in services.

    Args:
        transaction_manager: SessionTransactionManager or None.
        fn: Async callable that accepts session (or None) and returns a result.

    Returns:
        The result of fn(session) or fn(None).
    """
    if transaction_manager is None:
        return await fn(None)
    async with transaction_manager.transaction() as session:
        return await fn(session)


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
