import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from ugc_bot.domain.entities import UserReferralBinding
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import UserModel, UserReferralBindingModel
from ugc_bot.infrastructure.db.repositories.referrals import (
    SqlAlchemyUserReferralBindingRepository,
)


@pytest.mark.asyncio
async def test_capture_or_binding_races(legacy_pg):
    _, factory = legacy_pg
    referrer1, referrer2, referred = [uuid4() for _ in range(3)]
    now = datetime.now(timezone.utc)
    async with factory.begin() as session:
        session.add_all(
            [
                UserModel(
                    user_id=x,
                    messenger_type=MessengerType.TELEGRAM,
                    username="synthetic",
                    status=UserStatus.ACTIVE,
                    issue_count=0,
                    created_at=now,
                )
                for x in [referrer1, referrer2, referred]
            ]
        )
    repo = SqlAlchemyUserReferralBindingRepository(factory)
    ready = asyncio.Barrier(2)
    connections = set()

    async def bind(referrer):
        async with factory.begin() as session:
            connections.add(
                await session.scalar(text("SELECT pg_backend_pid()"))
            )
            await ready.wait()
            return await repo.save_or_get_existing(
                UserReferralBinding(
                    referrer_user_id=referrer,
                    referred_user_id=referred,
                    created_at=now,
                ),
                session=session,
            )

    results = await asyncio.gather(bind(referrer1), bind(referrer2))
    assert len(connections) == 2
    async with factory() as session:
        rows = (await session.scalars(select(UserReferralBindingModel))).all()
    assert len(rows) == 1
    assert sorted(created for _, created in results) == [False, True]
    assert results[0][0] == results[1][0]
    original = results[0][0]
    replay, created = await repo.save_or_get_existing(
        UserReferralBinding(
            referrer_user_id=referrer2
            if original.referrer_user_id == referrer1
            else referrer1,
            referred_user_id=referred,
            created_at=now,
        )
    )
    assert not created
    assert replay == original
