from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    OrderModel,
    PaymentModel,
    ReferralIncomeEntryModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.referrals import (
    SqlAlchemyReferralIncomeEntryRepository,
)


def income(order, referrer, referred):
    return ReferralIncomeEntryModel(
        entry_id=uuid4(),
        order_id=order,
        referrer_user_id=referrer,
        referred_user_id=referred,
        income_type="creator",
        currency="RUB",
        platform_revenue=Decimal("1000"),
        commission_rate=Decimal("0.10"),
        commission_amount=Decimal("100"),
    )


async def seed(factory):
    referrer, creator1, creator2, advertiser, order = [
        uuid4() for _ in range(5)
    ]
    now = datetime.now(timezone.utc)
    async with factory.begin() as session:
        for user_id in [referrer, creator1, creator2, advertiser]:
            session.add(
                UserModel(
                    user_id=user_id,
                    messenger_type=MessengerType.TELEGRAM,
                    username="synthetic",
                    status=UserStatus.ACTIVE,
                    issue_count=0,
                    created_at=now,
                )
            )
        await session.flush()
        session.add(
            OrderModel(
                order_id=order,
                advertiser_id=advertiser,
                order_type=OrderType.UGC_ONLY,
                product_link="https://example.test",
                offer_text="test",
                price=1000,
                bloggers_needed=2,
                status=OrderStatus.CLOSED,
                created_at=now,
            )
        )
        await session.flush()
        session.add(
            PaymentModel(
                payment_id=uuid4(),
                order_id=order,
                provider="yookassa_telegram",
                status=PaymentStatus.PAID,
                amount=1000,
                currency="RUB",
                external_id=uuid4().hex,
                created_at=now,
            )
        )
        for creator in [creator1, creator2]:
            session.add(
                UserReferralBindingModel(
                    referrer_user_id=referrer,
                    referred_user_id=creator,
                    created_at=now,
                )
            )
            session.add(
                InteractionModel(
                    interaction_id=uuid4(),
                    order_id=order,
                    blogger_id=creator,
                    advertiser_id=advertiser,
                    status=InteractionStatus.OK,
                    postpone_count=0,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.add(income(order, referrer, creator1))
    return referrer, creator1, creator2, advertiser, order


@pytest.mark.asyncio
async def test_second_creator_income_is_still_missing(legacy_pg):
    from ugc_bot.infrastructure.db.audit import register_audit_listener

    register_audit_listener()
    _, factory = legacy_pg
    _, _, creator2, _, order = await seed(factory)
    missing = await SqlAlchemyReferralIncomeEntryRepository(
        factory
    ).find_missing_creator_income()
    assert [(row.order_id, row.referred_user_id) for row in missing] == [
        (order, creator2)
    ]
