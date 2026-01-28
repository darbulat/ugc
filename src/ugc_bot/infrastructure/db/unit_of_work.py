"""Unit of Work implementation for SQLAlchemy.

The Unit of Work (UoW) centralizes transaction boundaries and makes it explicit
which operations participate in the same database transaction.
"""

from dataclasses import dataclass
from typing import Callable, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class UnitOfWork(Protocol):
    """A unit of work that owns a transactional session."""

    session: AsyncSession

    async def commit(self) -> None:
        """Commit the current transaction."""

    async def rollback(self) -> None:
        """Rollback the current transaction."""


UnitOfWorkFactory = Callable[[], "AsyncSqlAlchemyUnitOfWork"]


@dataclass(slots=True)
class AsyncSqlAlchemyUnitOfWork:
    """SQLAlchemy-based Unit of Work with an AsyncSession.

    Notes:
        - Use `async with uow:` to ensure commit/rollback and session close.
        - Repositories should use `uow.session` and must not commit themselves.
    """

    session_factory: async_sessionmaker[AsyncSession]
    session: AsyncSession | None = None

    async def __aenter__(self) -> "AsyncSqlAlchemyUnitOfWork":
        self.session = self.session_factory()
        await self.session.begin()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        assert self.session is not None
        try:
            if exc is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()

    @property
    def active_session(self) -> AsyncSession:
        """Return the active session (after entering the context)."""
        if self.session is None:
            raise RuntimeError(
                "UnitOfWork session is not initialized. Use 'async with'."
            )
        return self.session

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self.active_session.commit()

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        await self.active_session.rollback()
