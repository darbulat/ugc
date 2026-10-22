"""Wallet mutexes must not deadlock legitimate complaint foreign-key locks."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    ComplaintModel,
    InteractionModel,
    LegacyFinancialGuardModel,
    OrderModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.interactions import (
    SqlAlchemyInteractionRepository,
)
from ugc_bot.infrastructure.db.repositories.support import (
    SqlAlchemyComplaintRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager


@pytest.mark.asyncio
async def test_two_complaints_do_not_deadlock_wallet_fk_locks(
    financial_pg_engine,
):
    engine = create_async_engine(
        financial_pg_engine.url, pool_size=2, max_overflow=0
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    manager, creator, partner, client1, client2 = [uuid4() for _ in range(5)]
    order1, order2, interaction1, interaction2 = [uuid4() for _ in range(4)]
    now = datetime.now(timezone.utc)
    try:
        async with factory.begin() as session:
            session.add_all(
                [
                    UserModel(
                        user_id=user_id,
                        messenger_type=MessengerType.TELEGRAM,
                        username="synthetic-fk",
                        status=UserStatus.ACTIVE,
                        issue_count=0,
                        created_at=now,
                    )
                    for user_id in (manager, creator, partner, client1, client2)
                ]
            )
            await session.flush()
            session.add_all(
                [
                    OrderModel(
                        order_id=oid,
                        advertiser_id=advertiser,
                        order_type=OrderType.UGC_ONLY,
                        product_link="https://example.test",
                        offer_text="synthetic",
                        price=100,
                        bloggers_needed=1,
                        status=OrderStatus.ACTIVE,
                        created_at=now,
                        currency="RUB",
                    )
                    for oid, advertiser in (
                        (order1, client1),
                        (order2, client2),
                    )
                ]
            )
            await session.flush()
            # This referral graph is acyclic: partner -> creator -> client2.
            session.add_all(
                [
                    UserReferralBindingModel(
                        referrer_user_id=parent,
                        referred_user_id=child,
                        created_at=now,
                    )
                    for parent, child in (
                        (partner, creator),
                        (creator, client2),
                    )
                ]
            )
            session.add_all(
                [
                    InteractionModel(
                        interaction_id=iid,
                        order_id=oid,
                        blogger_id=blogger,
                        advertiser_id=advertiser,
                        status=InteractionStatus.PENDING,
                        postpone_count=0,
                        created_at=now,
                        updated_at=now,
                    )
                    for iid, oid, blogger, advertiser in (
                        (interaction1, order1, creator, client1),
                        (interaction2, order2, partner, client2),
                    )
                ]
            )
        tm = SessionTransactionManager(factory)
        complaints = ComplaintService(
            SqlAlchemyComplaintRepository(factory), transaction_manager=tm
        )
        interactions = InteractionService(
            SqlAlchemyInteractionRepository(factory), transaction_manager=tm
        )
        ready, backend_ids = asyncio.Barrier(2), set()

        async def report(oid, iid, reported):
            async with tm.transaction() as session:
                backend_ids.add(
                    await session.scalar(text("SELECT pg_backend_pid()"))
                )
                await complaints.create_complaint(
                    manager, reported, oid, "synthetic dispute", session=session
                )
                # Exactly the FK KEY SHARE locks acquired by the real command.
                await session.flush()
                await ready.wait()
                result = await interactions.record_advertiser_feedback(
                    iid, "⚠️ Проблема", session=session
                )
            await interactions.after_feedback_commit(result)
            return result

        results = await asyncio.gather(
            report(order1, interaction1, creator),
            report(order2, interaction2, partner),
            return_exceptions=True,
        )
        errors = [
            result for result in results if isinstance(result, BaseException)
        ]
        assert not errors, repr(errors)
        assert len(backend_ids) == 2
        for result in results:
            assert not isinstance(result, BaseException)
            assert result.status == InteractionStatus.ISSUE
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ComplaintModel)
                    .where(ComplaintModel.order_id.in_([order1, order2]))
                )
                == 2
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(LegacyFinancialGuardModel)
                    .where(
                        LegacyFinancialGuardModel.interaction_id.in_(
                            [interaction1, interaction2]
                        )
                    )
                )
                == 2
            )
    finally:
        await engine.dispose()
