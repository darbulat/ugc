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
    advertiser, booked, waitlisted, complimentary_creator = [
        uuid4() for _ in range(4)
    ]
    normal, free, test, old, historic = [uuid4() for _ in range(5)]
    with financial_pg_engine.begin() as db:
        db.execute(
            insert(UserModel),
            [
                {
                    "user_id": user_id,
                    "messenger_type": MessengerType.TELEGRAM,
                    "telegram_id": str(user_id.int)[-12:],
                    "username": str(user_id),
                    "telegram": "@UseMyContent"
                    if user_id == advertiser
                    else None,
                    "admin": user_id == advertiser,
                    "status": status,
                    "created_at": boundary,
                }
                for user_id, status in (
                    (advertiser, UserStatus.ACTIVE),
                    (booked, UserStatus.ACTIVE),
                    (waitlisted, UserStatus.BOT_BLOCKED),
                    (complimentary_creator, UserStatus.ACTIVE),
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
                for user_id in (booked, waitlisted, complimentary_creator)
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
                    if order_id in (old, historic, free)
                    else boundary,
                }
                for order_id in (normal, free, test, old, historic)
            ],
        )
        db.execute(
            insert(AuditLogModel),
            [
                dict(
                    entity_type="order_test_marker",
                    entity_id=test,
                    action=AuditAction.UPDATE,
                    new_values={"test": True},
                    changed_at=boundary,
                ),
                dict(
                    entity_type="order",
                    entity_id=free,
                    action=AuditAction.UPDATE,
                    new_values={"complimentary": True},
                    changed_at=boundary,
                ),
            ],
        )
        db.execute(
            insert(PaymentModel),
            [
                {
                    "order_id": order_id,
                    "provider": "manual" if order_id == normal else "synthetic",
                    "external_id": str(order_id),
                    "status": PaymentStatus.PAID,
                    "amount": 150,
                    "currency": "RUB",
                    "paid_at": boundary - timedelta(minutes=5)
                    if order_id == normal
                    else boundary,
                }
                for order_id in (normal, old, test)
            ],
        )
        db.execute(
            insert(OfferDispatchModel),
            [
                {
                    "order_id": order,
                    "blogger_id": creator,
                    "created_at": date,
                    "accepted": True,
                    "in_offer": in_offer,
                }
                for order, creator, date, in_offer in (
                    (normal, booked, boundary, True),
                    (normal, waitlisted, boundary, False),
                    (test, waitlisted, boundary, True),
                    (old, booked, start - timedelta(days=1), True),
                    (free, complimentary_creator, boundary, True),
                    (historic, booked, boundary, True),
                )
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
    assert charts["registrations_creators"] == [{"date": event_day, "count": 3}]
    assert charts["orders"] == [{"date": event_day, "count": 1}]
    assert charts["turnover"] == [
        {"date": event_day, "currency": "RUB", "amount": 300, "orders_paid": 2}
    ]
    assert dashboard["order_conversion"] == {
        "created": 1,
        "paid": 1,
        "percent": 100,
    }
    assert dashboard["previous_conversion"]["paid"] == 0
    assert dashboard["picked_creators_count"] == 2
    assert dashboard["admin_launches"] == [("usemycontent", 2)]
    assert dashboard["creator_metrics"] == {
        "profiles": 3,
        "telegram": 3,
        "bot_blocked": 1,
        "ever_worked": 2,
        "worked_period": 2,
        "first_period": 1,
        "returning_period": 1,
        "legacy_period": 2,
        "paid_started_period": 0,
    }
    assert dashboard["pending_payouts"] == 1
    assert dashboard["payout_requests"][0]["amount"] == 123.45
