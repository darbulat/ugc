"""Creator counts match the directory filters on the migrated database."""

from asyncio import gather
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    AuditAction,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.messenger_attribution import OFFER_CHANNELS
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    BloggerProfileModel,
    InteractionModel,
    OfferDispatchModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.interactions import (
    SqlAlchemyOfferDispatchRepository,
)
from ugc_bot.infrastructure.db.repositories.profiles import (
    SqlAlchemyBloggerProfileRepository,
)


@pytest.mark.asyncio
async def test_creator_base_counts_follow_the_same_segments_as_directory(
    financial_pg_engine,
):
    advertiser, both, tg_only, max_only, pending, older, deleted = [
        uuid4() for _ in range(7)
    ]
    order, duplicate_order = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    with financial_pg_engine.begin() as db:
        db.execute(
            insert(UserModel),
            [
                dict(
                    user_id=uid,
                    username=f"Creator {index}",
                    telegram_id=tg,
                    max_id=mx,
                    status=status,
                    messenger_type=MessengerType.TELEGRAM
                    if tg
                    else MessengerType.MAX,
                )
                for index, (uid, tg, mx, status) in enumerate(
                    (
                        (advertiser, "1000", None, UserStatus.ACTIVE),
                        (both, "1001", "2001", UserStatus.ACTIVE),
                        (tg_only, "1002", None, UserStatus.BOT_BLOCKED),
                        (max_only, None, "2003", UserStatus.ACTIVE),
                        (pending, "1004", None, UserStatus.ACTIVE),
                        (older, "1005", None, UserStatus.ACTIVE),
                        (deleted, "1006", None, UserStatus.DELETED),
                    )
                )
            ],
        )
        db.execute(
            insert(BloggerProfileModel),
            [
                dict(
                    user_id=uid,
                    instagram_url=f"https://instagram.com/t_{uid.hex}",
                    confirmed=uid not in (tg_only, pending),
                    agreement_confirmed_at=None if uid == tg_only else now,
                    topics={},
                    audience_gender=AudienceGender.ALL,
                    audience_age_min=18,
                    audience_age_max=40,
                    audience_geo="Москва",
                    price=100,
                )
                for uid in (both, tg_only, max_only, pending, older, deleted)
            ],
        )
        db.execute(
            insert(AuditLogModel),
            [
                dict(
                    entity_type=event,
                    entity_id=uid,
                    action=AuditAction.CREATE,
                    new_values={
                        "platform": platform,
                        f"{platform}_id": external,
                    },
                    changed_at=now - timedelta(minutes=minutes),
                )
                for uid, event, platform, external, minutes in (
                    (both, "bot_unavailable", "telegram", "1001", 5),
                    (both, "bot_available", "telegram", "1001", 3),
                    (both, "bot_unavailable", "max", "2001", 2),
                    (max_only, "bot_unavailable", "max", "old-max-id", 1),
                )
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
                    status=OrderStatus.ACTIVE
                    if oid == order
                    else OrderStatus.CLOSED,
                    created_at=now - timedelta(days=120),
                )
                for oid in (order, duplicate_order)
            ],
        )
        db.execute(
            insert(OfferDispatchModel),
            [
                dict(
                    order_id=oid,
                    blogger_id=uid,
                    accepted=accepted,
                    in_offer=in_offer,
                    created_at=now - timedelta(days=days),
                )
                for oid, uid, accepted, in_offer, days in (
                    (order, both, True, True, 2),
                    (duplicate_order, both, True, True, 1),
                    (order, tg_only, None, False, 2),
                    (order, pending, False, False, 2),
                    (order, max_only, True, False, 40),
                    (duplicate_order, older, True, True, 100),
                    (duplicate_order, max_only, True, True, 100),
                    (order, deleted, True, True, 1),
                )
            ],
        )
        db.execute(
            insert(OFFER_CHANNELS),
            [
                dict(
                    order_id=oid,
                    blogger_id=uid,
                    telegram_sent_at=now - timedelta(days=days)
                    if (oid, uid) == (order, both)
                    else None,
                    max_sent_at=now - timedelta(days=days)
                    if uid in (both, max_only)
                    else None,
                    response_channel="max"
                    if (oid, uid) in ((order, both), (order, pending))
                    else None,
                    response_at=now - timedelta(days=days)
                    if (oid, uid) in ((order, both), (order, pending))
                    else None,
                )
                for oid, uid, days in (
                    (order, both, 2),
                    (duplicate_order, both, 1),
                    (order, pending, 2),
                    (order, max_only, 40),
                    (duplicate_order, max_only, 100),
                )
            ],
        )
        db.execute(
            insert(InteractionModel),
            [
                dict(
                    order_id=duplicate_order,
                    blogger_id=uid,
                    advertiser_id=advertiser,
                    status=status,
                    created_at=now - timedelta(days=100),
                    updated_at=now - timedelta(days=100),
                )
                for uid, status in (
                    (older, InteractionStatus.PENDING),
                    (max_only, InteractionStatus.OK),
                )
            ],
        )

    engine = create_async_engine(financial_pg_engine.url)
    sessions = async_sessionmaker(engine)
    profile_repo = SqlAlchemyBloggerProfileRepository(sessions)
    dispatch_repo = SqlAlchemyOfferDispatchRepository(sessions)
    service = AdminDashboardService(
        sessions,
        "Europe/Moscow",
        DelayThresholds(7, 24, 48, 7),
    )
    try:
        await profile_repo.record_registration_channel(
            max_only, MessengerType.MAX, now - timedelta(days=1), session=None
        )
        await profile_repo.record_registration_channel(
            max_only, MessengerType.TELEGRAM, now, session=None
        )
        counts = await service.get_creator_base("30d")
        assert counts == {
            "profiles": 5,
            "registered": 3,
            "no_agreement": 1,
            "no_instagram": 1,
            "registered_telegram": 2,
            "registered_max": 2,
            "registered_both": 1,
            "registered_max_only": 1,
            "telegram_account": 4,
            "max_account": 2,
            "telegram_available": 1,
            "telegram_unavailable": 1,
            "telegram_unknown": 2,
            "max_available": 0,
            "max_unavailable": 1,
            "max_unknown": 1,
            "offered": 3,
            "accepted": 1,
            "worked": 2,
            "responded": 2,
            "offered_via_max": 1,
            "max_only_offer": 1,
            "max_only_reached": 0,
            "responded_via_max": 2,
            "registered_via_max": 1,
        }
        for segment, count in counts.items():
            listing = await service.list_creators(
                "all", False, False, base_segment=segment, work_period="30d"
            )
            assert listing["total"] == count, segment
        assert (await service.get_creator_base("7d"))["offered"] == 3
        counts_90d = await service.get_creator_base("90d")
        assert counts_90d["accepted"] == 2
        assert counts_90d["offered_via_max"] == 2
        assert counts_90d["max_only_reached"] == 1
        assert (await service.get_creator_base("all"))["worked"] == 3

        await profile_repo.record_registration_channel(
            tg_only, MessengerType.MAX, None, session=None
        )
        counts_before_consent = await service.get_creator_base("30d")
        assert counts_before_consent["registered_via_max"] == 1
        no_consent = await profile_repo.get_by_user_id(tg_only)
        assert no_consent is not None
        await profile_repo.save(
            replace(no_consent, confirmed=True, agreement_confirmed_at=now)
        )
        counts_after_consent = await service.get_creator_base("30d")
        assert counts_after_consent["registered_via_max"] == 2

        await gather(
            dispatch_repo.record_sent(
                order, tg_only, channel=MessengerType.TELEGRAM
            ),
            dispatch_repo.record_sent(
                order, tg_only, channel=MessengerType.MAX
            ),
        )
        await dispatch_repo.record_response(
            order, tg_only, True, True, channel=MessengerType.MAX
        )
        statement = select(OFFER_CHANNELS).where(
            OFFER_CHANNELS.c.order_id == order,
            OFFER_CHANNELS.c.blogger_id == tg_only,
        )
        with financial_pg_engine.connect() as db:
            saved = db.execute(statement).one()
        assert saved.max_sent_at and saved.telegram_sent_at
        assert saved.response_at and saved.response_channel == MessengerType.MAX
        await dispatch_repo.record_sent(
            order, tg_only, channel=MessengerType.MAX
        )
        await dispatch_repo.record_response(
            order, tg_only, True, True, channel=MessengerType.TELEGRAM
        )
        with financial_pg_engine.connect() as db:
            repeated = db.execute(statement).one()
            assert db.scalar(
                select(OfferDispatchModel.in_offer).where(
                    OfferDispatchModel.order_id == order,
                    OfferDispatchModel.blogger_id == tg_only,
                )
            )
        assert repeated == saved
    finally:
        await engine.dispose()
