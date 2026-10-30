"""Paid intake retains the full brief and applies city/platform selection."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.helpers.factories import (
    create_test_blogger_profile,
    create_test_user,
)
from tests.postgres_financial.test_order_intake import command, service
from tests.postgres_financial.test_order_intake import intake_env as _intake_env
from ugc_bot.domain.enums import OrderType, WorkFormat
from ugc_bot.domain.order_targeting import OrderTargeting
from ugc_bot.infrastructure.db.social_models import SocialAccountModel

intake_env = _intake_env


@pytest.mark.asyncio
async def test_paid_brief_replay_and_actual_city_platform_matching(intake_env):
    env = intake_env
    target = OrderTargeting(
        city="Москва",
        platforms=("youtube",),
        content_usage="Вертикальное видео 30 секунд",
        brief_link="https://example.com/detailed-brief",
    )
    requested = replace(
        command(env), targeting=target, order_type=OrderType.UGC_PLUS_PLACEMENT
    )
    result = await service(env).create(requested)
    assert await service(env).create(requested) == result
    assert result.targeting["platforms"] == ["youtube"]
    saved = await env["repos"]["order_repo"].get_by_id(result.order_id)
    assert saved.order_type == OrderType.UGC_PLUS_PLACEMENT
    assert (
        saved.geography == "Москва"
        and saved.content_usage == target.content_usage
    )
    assert saved.brief_link == target.brief_link and saved.filter_by_placement
    ids = []
    for city, platform in [
        ("Москва", "youtube"),
        ("Казань", "youtube"),
        ("Москва", "tiktok"),
    ]:
        user = await create_test_user(
            env["repos"]["user_repo"],
            external_id=str(uuid4().int % 10**12 + 1),
            country="ru",
        )
        await create_test_blogger_profile(
            env["repos"]["blogger_repo"],
            user.user_id,
            city=city,
            instagram_url="https://instagram.com/" + user.user_id.hex,
            work_format=WorkFormat.ADS_IN_ACCOUNT,
        )
        with Session(env["pg"]) as db, db.begin():
            db.add(
                SocialAccountModel(
                    account_id=uuid4(),
                    user_id=user.user_id,
                    platform=platform,
                    url="https://example.com/" + user.user_id.hex,
                    handle=user.user_id.hex,
                    verified=False,
                    work_format="ads_in_account",
                    created_at=env["clock"].at,
                    updated_at=env["clock"].at,
                )
            )
        ids.append(user.user_id)
    tm = env["container"].transaction_manager
    async with tm.transaction() as db:
        assert (
            await env["repos"]["order_intake_repo"].filter_candidates(
                result.order_id, ids, session=db
            )
            == ids[:1]
        )
        assert (
            await env["repos"]["order_intake_repo"].filter_candidates(
                uuid4(), ids, session=db
            )
            == ids
        )
    dispatcher = env["container"].build_bot_services()
    assert (
        await dispatcher["offer_dispatch_service"].count_eligible_bloggers(
            result.order_id
        )
        == 1
    )
    with pytest.raises(ValueError, match="idempotency"):
        await service(env).create(
            replace(requested, targeting=replace(target, platforms=("tiktok",)))
        )


@pytest.mark.asyncio
async def test_legacy_editor_cannot_rewrite_financial_intake(intake_env):
    from ugc_bot.application.errors import OrderCreationError

    env = intake_env
    intake = service(env)
    requested = replace(
        command(env),
        targeting=OrderTargeting(city="Москва", platforms=("youtube",)),
    )
    result = await intake.create(requested)
    saved = await env["repos"]["order_repo"].get_by_id(result.order_id)
    with pytest.raises(
        OrderCreationError, match="financial_order_intake_immutable"
    ):
        await intake.orders.update_order(
            order_id=result.order_id,
            advertiser_id=requested.client_id,
            product_link=saved.product_link,
            offer_text=saved.offer_text,
            barter_description=saved.barter_description,
            price=saved.price,
            bloggers_needed=saved.bloggers_needed,
            order_type=OrderType.UGC_PLUS_PLACEMENT,
            geography="Казань",
        )
    assert await env["repos"]["order_repo"].get_by_id(result.order_id) == saved
    assert (await intake.create(requested)).targeting["city"] == "Москва"


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["telegram", "max"])
@pytest.mark.parametrize(
    "geography,queries,matched",
    [
        ("Россия", [("россия", None, "")], (0, 1)),
        ("Татарстан", [("татарстан", None, "")], (0, 1)),
        (
            "Москва, Казань",
            [("москва", None, ""), ("казань", None, "")],
            (0, 1),
        ),
        ("весь мир", [], (0, 1, 2)),
    ],
)
async def test_bot_free_text_geography_is_geocoded_and_matches_places(
    intake_env, channel, geography, queries, matched
):
    from ugc_bot.bot.customer_intake import command_from_state
    from ugc_bot.domain.enums import MessengerType

    env = intake_env
    ids = []
    for city, x in [("Москва", 1), ("Казань", 2), ("Берлин", 10)]:
        user = await create_test_user(
            env["repos"]["user_repo"],
            external_id=str(uuid4().int % 10**12 + 1),
            country="ru",
        )
        await create_test_blogger_profile(
            env["repos"]["blogger_repo"],
            user.user_id,
            city=city,
            instagram_url="https://instagram.com/" + user.user_id.hex,
        )
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                text(
                    "UPDATE blogger_profiles SET location_geometry = "
                    "ST_GeomFromText(:point, 4326) WHERE user_id = :id"
                ),
                {"point": f"MULTIPOINT(({x} 1))", "id": user.user_id},
            )
        ids.append(user.user_id)

    initial = command(env)
    bot_command = command_from_state(
        {
            "user_id": str(initial.client_id),
            "intake_operation_key": initial.operation_key,
            "intake_policy": initial.policy_version,
            "product_link": initial.product_link,
            "offer_text": initial.offer_text,
            "price": 999,
            "intake_due_at": initial.selection_due_at.isoformat(),
            "bloggers_needed": 10,
            "order_type": "ugc_only",
            "accompaniment_count": 0,
            "geography": geography,
        },
        SimpleNamespace(
            user=SimpleNamespace(
                messenger_type=MessengerType(channel), external_id="123"
            )
        ),
    )
    intake = service(env)
    geocoder = SimpleNamespace(
        get_multipolygon_wkt_for_queries=AsyncMock(
            return_value="MULTIPOLYGON(((0 0, 3 0, 3 3, 0 3, 0 0)))"
        )
    )
    intake.orders.geocoder = geocoder
    result = await intake.create(bot_command)
    order = await env["repos"]["order_repo"].get_by_id(result.order_id)
    assert order.geography == geography
    if queries:
        geocoder.get_multipolygon_wkt_for_queries.assert_awaited_once_with(
            queries
        )
        assert order.location_geometry is not None
    else:
        geocoder.get_multipolygon_wkt_for_queries.assert_not_awaited()
        assert order.location_geometry is None
    async with env["container"].transaction_manager.transaction() as db:
        located = await env["repos"]["blogger_repo"].list_confirmed_user_ids(
            session=db, location_geometry_wkt=order.location_geometry
        )
        eligible = await env["repos"]["order_intake_repo"].filter_candidates(
            result.order_id, [uid for uid in ids if uid in located], session=db
        )
    assert eligible == [ids[index] for index in matched]


@pytest.mark.asyncio
async def test_bot_retry_replays_receipt_written_before_geography_fix(
    intake_env,
):
    env = intake_env
    intake = service(env)
    old_command = command(env, targeting=OrderTargeting(city="Россия"))
    old_result = await intake.create(old_command)
    fixed_command = replace(
        old_command, targeting=OrderTargeting(geography="Россия")
    )
    assert await intake.create(fixed_command) == old_result
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await intake.create(
            replace(fixed_command, targeting=OrderTargeting(geography="Казань"))
        )


@pytest.mark.asyncio
async def test_geocoding_exception_leaves_no_financial_order(intake_env):
    env = intake_env
    intake = service(env)
    requested = command(env, targeting=OrderTargeting(geography="Россия"))
    intake.orders.geocoder = SimpleNamespace(
        get_multipolygon_wkt_for_queries=AsyncMock(
            side_effect=RuntimeError("geocoder offline")
        )
    )
    with pytest.raises(ValueError, match="geography_unavailable"):
        await intake.create(requested)
    assert (
        await env["repos"]["order_repo"].get_by_id(requested.order_id) is None
    )
