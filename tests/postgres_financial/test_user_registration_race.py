"""Real PostgreSQL coverage for concurrent native user registration."""

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from ugc_bot.infrastructure.db.session import (
    SessionTransactionManager,
    create_async_db_engine,
)


@pytest.mark.asyncio
async def test_concurrent_registration_recovers_commit_unique_violation(
    financial_pg_engine,
):
    """Two real sessions racing for one Telegram ID return the same user."""
    external_id = f"race-{uuid4()}"
    async_engine = create_async_db_engine(
        financial_pg_engine.url.render_as_string(hide_password=False),
        pool_size=2,
        max_overflow=0,
    )
    sessions = async_sessionmaker(async_engine, expire_on_commit=False)
    repository = SqlAlchemyUserRepository(sessions)
    both_absent = asyncio.Event()
    first_reads = 0
    read_lock = asyncio.Lock()

    class BarrierRepository:
        def __getattr__(self, name):
            return getattr(repository, name)

        async def get_by_external(self, candidate, messenger, session=None):
            nonlocal first_reads
            user = await repository.get_by_external(
                candidate, messenger, session=session
            )
            if candidate == external_id and user is None:
                async with read_lock:
                    first_reads += 1
                    if first_reads == 2:
                        both_absent.set()
                await asyncio.wait_for(both_absent.wait(), timeout=10)
            return user

    service = UserRoleService(
        user_repo=cast(Any, BarrierRepository()),
        transaction_manager=SessionTransactionManager(sessions),
    )
    try:
        first, second = await asyncio.gather(
            service.set_user(external_id, MessengerType.TELEGRAM, "first"),
            service.set_user(external_id, MessengerType.TELEGRAM, "second"),
        )
        assert first.user_id == second.user_id
        async with sessions() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(UserModel)
                .where(UserModel.telegram_id == external_id)
            )
        assert count == 1
    finally:
        await async_engine.dispose()
