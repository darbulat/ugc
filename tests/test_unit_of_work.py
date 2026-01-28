"""Tests for Unit of Work implementation."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text

from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.infrastructure.db.unit_of_work import AsyncSqlAlchemyUnitOfWork


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[object]:
    """Create an async session factory and dispose engine after test."""

    factory = create_session_factory("sqlite:///:memory:")
    try:
        yield factory
    finally:
        await factory.kw["bind"].dispose()  # type: ignore[no-any-return]


@pytest.mark.asyncio
async def test_uow_commit(session_factory) -> None:
    """UoW commits changes when context exits cleanly."""

    uow = AsyncSqlAlchemyUnitOfWork(session_factory=session_factory)
    async with uow:
        await uow.active_session.execute(
            text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        )
        await uow.active_session.execute(text("INSERT INTO items (value) VALUES ('a')"))

    async with session_factory() as session:
        result = await session.execute(text("SELECT count(*) FROM items"))
        assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_uow_rollback(session_factory) -> None:
    """UoW rolls back changes when an exception is raised."""

    async with session_factory() as session:
        await session.execute(
            text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
        )
        await session.commit()

    with pytest.raises(RuntimeError):
        uow = AsyncSqlAlchemyUnitOfWork(session_factory=session_factory)
        async with uow:
            await uow.active_session.execute(
                text("INSERT INTO items (value) VALUES ('a')")
            )
            raise RuntimeError("boom")

    async with session_factory() as session:
        result = await session.execute(text("SELECT count(*) FROM items"))
        assert result.scalar_one() == 0
