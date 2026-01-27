"""Tests for database session helpers."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ugc_bot.infrastructure.db.session import (
    SessionTransactionManager,
    create_db_engine,
    create_session_factory,
)


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[object]:
    """Create an async session factory and dispose engine after test.

    Without explicit disposal, the underlying `aiosqlite` worker threads may
    linger until interpreter shutdown, which can produce noisy logs or even
    hang the process on exit in some environments.
    """

    factory = create_session_factory("sqlite:///:memory:")
    try:
        yield factory
    finally:
        # `async_sessionmaker` stores engine in `kw["bind"]`
        await factory.kw["bind"].dispose()  # type: ignore[no-any-return]


def test_create_db_engine() -> None:
    """Create database engine."""

    engine = create_db_engine("sqlite:///:memory:")
    assert isinstance(engine, Engine)


@pytest.mark.asyncio
async def test_create_session_factory(session_factory) -> None:
    """Create session factory."""

    async with session_factory() as session:
        assert session is not None


@pytest.mark.asyncio
async def test_transaction_manager_commit(session_factory) -> None:
    """Transaction manager commits changes."""

    manager = SessionTransactionManager(session_factory)

    async with manager.transaction() as session:
        await session.execute(
            text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        )
        await session.execute(text("INSERT INTO items (value) VALUES ('a')"))

    async with session_factory() as session:
        result = await session.execute(text("SELECT count(*) FROM items"))
        count = result.scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_transaction_manager_rollback(session_factory) -> None:
    """Transaction manager rolls back on error."""

    manager = SessionTransactionManager(session_factory)

    async with session_factory() as session:
        await session.execute(
            text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        )
        await session.commit()

    with pytest.raises(RuntimeError):
        async with manager.transaction() as session:
            await session.execute(text("INSERT INTO items (value) VALUES ('a')"))
            raise RuntimeError("boom")

    async with session_factory() as session:
        result = await session.execute(text("SELECT count(*) FROM items"))
        count = result.scalar_one()
    assert count == 0
