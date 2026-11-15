"""Test activation windows and repeat payments against PostgreSQL."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.admin.business_metrics import cohort_metrics
from ugc_bot.domain.enums import (
    AudienceGender,
    AuditAction,
    MessengerType,
    OrderStatus,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    BloggerProfileModel,
    OfferDispatchModel,
    OrderModel,
    PaymentModel,
    UserModel,
)


@pytest.mark.asyncio
async def test_cohorts_count_first_events_and_distinct_repeat_customers(
    financial_pg_engine,
) -> None:
    as_of = datetime(2026, 10, 1, tzinfo=timezone.utc)
    old = as_of - timedelta(days=200)
    recent = as_of - timedelta(days=10)
    fast, late, deadline, new_creator, no_order = [uuid4() for _ in range(5)]
    (
        repeat,
        slow,
        free_only,
        new_customer,
        single,
        prepaid,
        cutoff,
        no_profile,
    ) = [uuid4() for _ in range(8)]
    creators = (fast, late, deadline, new_creator, no_order)
    customers = (repeat, slow, free_only, new_customer, single, prepaid, cutoff)
    created_at = dict.fromkeys((*creators, *customers, no_profile), old)
    created_at.update(
        {
            new_creator: recent,
            new_customer: recent,
            single: as_of - timedelta(days=50),
        }
    )

    with financial_pg_engine.begin() as db:
        db.execute(
            insert(UserModel),
            [
                dict(
                    user_id=user,
                    messenger_type=MessengerType.TELEGRAM,
                    username="synthetic",
                    status=UserStatus.ACTIVE,
                    created_at=at,
                )
                for user, at in created_at.items()
            ],
        )
        db.execute(
            insert(BloggerProfileModel),
            [
                dict(
                    user_id=creator,
                    instagram_url=f"https://instagram.com/{creator.hex}",
                    topics={},
                    audience_gender=AudienceGender.ALL,
                    audience_age_min=18,
                    audience_age_max=65,
                    audience_geo="synthetic",
                    price=100,
                    created_at=as_of - timedelta(days=1),
                )
                for creator in creators
            ],
        )
        db.execute(
            insert(AdvertiserProfileModel),
            [
                dict(
                    user_id=customer,
                    contact="synthetic",
                    created_at=as_of - timedelta(days=1),
                )
                for customer in customers
            ],
        )

        launch = uuid4()
        orders = [
            dict(
                order_id=launch,
                advertiser_id=free_only,
                created_at=old,
                complimentary=True,
            ),
        ]
        payments = []
        markers = []
        scenarios = (
            # Customer, days after registration, amount, status, marked test.
            (repeat, 2, 100, PaymentStatus.PAID, True),
            (repeat, 9, 100, PaymentStatus.PAID, False),
            (repeat, 20, 100, PaymentStatus.PAID, False),
            (repeat, 25, 100, PaymentStatus.PAID, False),
            (slow, 31, 100, PaymentStatus.PAID, False),
            (slow, 121, 100, PaymentStatus.PAID, False),
            (free_only, 2, 0, PaymentStatus.PAID, False),
            (free_only, 4, 100, PaymentStatus.PAID, True),
            (free_only, 5, 100, PaymentStatus.PENDING, False),
            (new_customer, 2, 100, PaymentStatus.PAID, False),
            (new_customer, 2, 100, PaymentStatus.PAID, False),
            (single, 6, 100, PaymentStatus.PAID, False),
            (single, 51, 100, PaymentStatus.PAID, False),
            (prepaid, -1, 100, PaymentStatus.PAID, False),
            (prepaid, 3, 100, PaymentStatus.PAID, False),
            (cutoff, 30, 100, PaymentStatus.PAID, False),
            (no_profile, 4, 100, PaymentStatus.PAID, False),
        )
        for customer, offset, amount, status, is_test in scenarios:
            order = uuid4()
            payment_time = created_at[customer] + timedelta(days=offset)
            orders.append(
                dict(
                    order_id=order,
                    advertiser_id=customer,
                    created_at=max(created_at[customer], payment_time),
                    complimentary=False,
                )
            )
            payments.append(
                dict(
                    order_id=order,
                    provider="manual" if offset < 0 else "synthetic",
                    external_id=str(order),
                    status=status,
                    amount=amount,
                    currency="RUB",
                    paid_at=payment_time,
                )
            )
            if is_test:
                markers.append(
                    dict(
                        entity_type="order_test_marker",
                        entity_id=order,
                        action=AuditAction.UPDATE,
                        new_values={"test": True},
                    )
                )

        db.execute(
            insert(OrderModel),
            [
                dict(
                    **order,
                    product_link="https://example.test",
                    offer_text="Synthetic order",
                    price=100,
                    bloggers_needed=1,
                    status=OrderStatus.CLOSED,
                )
                for order in orders
            ],
        )
        db.execute(insert(PaymentModel), payments)
        db.execute(insert(AuditLogModel), markers)
        db.execute(
            insert(OfferDispatchModel),
            [
                dict(
                    order_id=order,
                    blogger_id=creator,
                    created_at=created_at[creator] + timedelta(days=offset),
                    accepted=True,
                    in_offer=in_offer,
                )
                for order, creator, offset, in_offer in (
                    (launch, fast, 20, True),
                    (launch, late, 31, True),
                    (markers[0]["entity_id"], late, 1, True),
                    (orders[2]["order_id"], late, 5, False),
                    (launch, deadline, 30, True),
                    (launch, new_creator, 1, True),
                )
            ],
        )

    engine = create_async_engine(financial_pg_engine.url)
    try:
        factory = async_sessionmaker(engine)
        async with factory() as session:
            metrics = await cohort_metrics(session, as_of)
    finally:
        await engine.dispose()

    assert metrics == {
        "creator_activation": {"eligible": 4, "converted": 1, "percent": 25},
        "customer_activation": {"eligible": 6, "converted": 2, "percent": 33.3},
        "customer_repeat_90d": {"eligible": 5, "converted": 2, "percent": 40},
        "repeat_customers": 4,
        "paying_customers": 7,
    }
