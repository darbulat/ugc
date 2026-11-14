"""Verify dashboard periods and business metrics against the real schema."""

from datetime import timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
    dashboard_period_window,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    AuditAction,
    MessengerType,
    OrderStatus,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    BloggerProfileModel,
    OfferDispatchModel,
    OrderModel,
    PaymentModel,
    PayoutRequestModel,
    UserModel,
)


@pytest.mark.asyncio
async def test_dashboard_calendar_conversion_creator_activity_and_payouts(
    financial_pg_engine,
) -> None:
    """Count only placed legacy offers and eligible conversion candidates."""
    zone = ZoneInfo("Europe/Moscow")
    start = dashboard_period_window("30d", zone).current_start
    boundary = (start + timedelta(days=2, minutes=20)).astimezone(timezone.utc)
    advertiser, booked, waitlisted = [uuid4() for _ in range(3)]
    normal, free, test, old = [uuid4() for _ in range(4)]
    with financial_pg_engine.begin() as db:
        db.execute(
            insert(UserModel),
            [
                {
                    "user_id": user_id,
                    "messenger_type": MessengerType.TELEGRAM,
                    "telegram_id": str(user_id.int)[-12:],
                    "username": str(user_id),
                    "status": status,
                    "created_at": boundary,
                }
                for user_id, status in (
                    (advertiser, UserStatus.ACTIVE),
                    (booked, UserStatus.ACTIVE),
                    (waitlisted, UserStatus.BOT_BLOCKED),
                )
            ],
        )
        db.execute(
            insert(BloggerProfileModel),
            [
                {
                    "user_id": user_id,
                    "instagram_url": f"https://instagram.com/test_{user_id.hex}",
                    "topics": {},
                    "audience_gender": AudienceGender.ALL,
                    "audience_age_min": 18,
                    "audience_age_max": 40,
                    "audience_geo": "Москва",
                    "price": 100,
                }
                for user_id in (booked, waitlisted)
            ],
        )
        db.execute(
            insert(OrderModel),
            [
                {
                    "order_id": order_id,
                    "advertiser_id": advertiser,
                    "product_link": "https://example.test/product",
                    "offer_text": "Синтетический заказ",
                    "price": 150,
                    "bloggers_needed": 1,
                    "status": OrderStatus.ACTIVE,
                    "complimentary": order_id == free,
                    "created_at": start - timedelta(days=2)
                    if order_id == old
                    else boundary,
                }
                for order_id in (normal, free, test, old)
            ],
        )
        db.execute(
            insert(AuditLogModel).values(
                entity_type="order_test_marker",
                entity_id=test,
                action=AuditAction.UPDATE,
                new_values={"test": True},
            )
        )
        db.execute(
            insert(PaymentModel),
            [
                {
                    "order_id": order_id,
                    "provider": "synthetic",
                    "external_id": str(order_id),
                    "status": PaymentStatus.PAID,
                    "amount": 150,
                    "currency": "RUB",
                    "paid_at": boundary,
                }
                for order_id in (normal, old, test)
            ],
        )
        db.execute(
            insert(OfferDispatchModel),
            [
                {
                    "order_id": normal,
                    "blogger_id": creator,
                    "created_at": boundary,
                    "accepted": True,
                    "in_offer": creator == booked,
                }
                for creator in (booked, waitlisted)
            ],
        )
        db.execute(
            insert(PayoutRequestModel).values(
                user_id=booked,
                amount=123.45,
                currency="RUB",
            )
        )

    engine = create_async_engine(financial_pg_engine.url)
    try:
        service = AdminDashboardService(
            async_sessionmaker(engine),
            zone.key,
            DelayThresholds(3, 24, 48, 7),
        )
        charts = await service.get_dashboard_charts("30d")
        dashboard = await service.get_dashboard("30d")
    finally:
        await engine.dispose()

    event_day = boundary.astimezone(zone).date().isoformat()
    assert len(charts["dates"]) == 30
    assert charts["dates"][0] == start.date().isoformat()
    assert event_day != boundary.date().isoformat()
    assert charts["registrations_creators"] == [{"date": event_day, "count": 2}]
    assert charts["orders"] == [{"date": event_day, "count": 2}]
    assert charts["turnover"] == [
        {"date": event_day, "currency": "RUB", "amount": 300, "orders_paid": 2}
    ]
    assert dashboard["order_conversion"] == {
        "created": 1,
        "paid": 1,
        "percent": 100,
    }
    assert dashboard["previous_conversion"]["paid"] == 0
    assert dashboard["creator_metrics"] == {
        "profiles": 2,
        "telegram": 2,
        "bot_blocked": 1,
        "ever_worked": 1,
        "worked_period": 1,
    }
    assert dashboard["pending_payouts"] == 1
    assert dashboard["payout_requests"][0]["amount"] == 123.45
