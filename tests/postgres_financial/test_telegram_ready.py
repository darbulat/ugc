"""Telegram matching readiness from the order and bot event histories."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    AuditAction,
    MessengerType,
    OrderStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.messenger_attribution import OFFER_CHANNELS
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    BloggerProfileModel,
    OfferDispatchModel,
    OrderModel,
    UserModel,
)


@pytest.mark.asyncio
async def test_telegram_ready_uses_last_successful_offer_and_block(
    financial_pg_engine,
):
    now = datetime.now(timezone.utc)
    earlier = now - timedelta(minutes=2)
    recent = now - timedelta(minutes=1)
    advertiser, order, second_order, test_order, deleted_order = (
        uuid4() for _ in range(5)
    )
    cases = {
        name: uuid4()
        for name in (
            "sent",
            "still_blocked",
            "reached_again",
            "tied",
            "explicit_unblock",
            "max_only_send",
            "old_account_block",
            "legacy_block",
            "incomplete",
            "deleted",
            "unlinked",
            "test_send",
            "deleted_order_send",
            "unknown",
        )
    }
    external_ids = {name: str(index + 100) for index, name in enumerate(cases)}
    with financial_pg_engine.begin() as db:
        db.execute(
            insert(UserModel),
            [
                {
                    "user_id": uid,
                    "username": name,
                    "telegram_id": external_ids.get(name)
                    if name != "unlinked"
                    else None,
                    "status": {
                        "legacy_block": UserStatus.BOT_BLOCKED,
                        "deleted": UserStatus.DELETED,
                    }.get(name, UserStatus.ACTIVE),
                    "messenger_type": MessengerType.TELEGRAM,
                }
                for name, uid in {"advertiser": advertiser, **cases}.items()
            ],
        )
        db.execute(
            insert(BloggerProfileModel),
            [
                dict(
                    user_id=uid,
                    instagram_url=f"https://instagram.com/{name}",
                    confirmed=name != "incomplete",
                    agreement_confirmed_at=earlier,
                    topics={},
                    audience_gender=AudienceGender.ALL,
                    audience_age_min=18,
                    audience_age_max=40,
                    audience_geo="Москва",
                    price=100,
                )
                for name, uid in cases.items()
            ],
        )
        db.execute(
            insert(OrderModel),
            [
                dict(
                    order_id=oid,
                    advertiser_id=advertiser,
                    product_link="https://example.test/product",
                    offer_text="Заказ",
                    price=150,
                    bloggers_needed=2,
                    status=OrderStatus.DELETED
                    if oid == deleted_order
                    else OrderStatus.CLOSED,
                )
                for oid in (order, second_order, test_order, deleted_order)
            ],
        )
        events = [
            dict(
                entity_type=event,
                entity_id=cases[name],
                action=AuditAction.CREATE,
                new_values={
                    "platform": "telegram",
                    "telegram_id": "replaced"
                    if name == "old_account_block"
                    else external_ids[name],
                },
                changed_at=timestamp,
            )
            for name, event, timestamp in (
                ("still_blocked", "bot_unavailable", now),
                ("reached_again", "bot_unavailable", recent),
                ("tied", "bot_unavailable", recent),
                ("explicit_unblock", "bot_unavailable", earlier),
                ("explicit_unblock", "bot_available", recent),
                ("old_account_block", "bot_unavailable", now),
            )
        ]
        db.execute(
            insert(AuditLogModel),
            [
                *events,
                dict(
                    entity_type="order_test_marker",
                    entity_id=test_order,
                    action=AuditAction.CREATE,
                    new_values={"test": True},
                    changed_at=now,
                ),
            ],
        )
        sends = [
            dict(
                order_id=oid,
                blogger_id=cases[name],
                telegram_sent_at=None if name == "max_only_send" else sent_at,
                max_sent_at=sent_at if name == "max_only_send" else None,
            )
            for oid, name, sent_at in (
                (order, "sent", recent),
                (order, "still_blocked", recent),
                (order, "reached_again", earlier),
                (second_order, "reached_again", now),
                (order, "tied", recent),
                (order, "max_only_send", recent),
                (order, "old_account_block", recent),
                (order, "legacy_block", recent),
                (order, "incomplete", recent),
                (order, "deleted", recent),
                (order, "unlinked", recent),
                (test_order, "test_send", recent),
                (deleted_order, "deleted_order_send", recent),
            )
        ]
        db.execute(
            insert(OfferDispatchModel),
            [
                dict(order_id=send["order_id"], blogger_id=send["blogger_id"])
                for send in sends
            ],
        )
        db.execute(insert(OFFER_CHANNELS), sends)

    engine = create_async_engine(financial_pg_engine.url)
    service = AdminDashboardService(
        async_sessionmaker(engine),
        "Europe/Moscow",
        DelayThresholds(7, 24, 48, 7),
    )
    try:
        ready = await service.list_creators(
            "all", False, False, base_segment="telegram_ready"
        )
        assert ready["total"] == 4
        assert {item["user_id"] for item in ready["items"]} == {
            str(cases[name])
            for name in (
                "sent",
                "reached_again",
                "explicit_unblock",
                "old_account_block",
            )
        }
        blocked = await service.list_creators(
            "all", False, False, status="bot_blocked"
        )
        assert {item["user_id"] for item in blocked["items"]} == {
            str(cases[name])
            for name in ("still_blocked", "tied", "legacy_block")
        }
        counts = await service.get_creator_base("all")
        assert (
            counts["telegram_available"] == 5
        )  # Includes incomplete registration.
        assert counts["telegram_unavailable"] == 3
        assert counts["telegram_unknown"] == 4
    finally:
        await engine.dispose()
