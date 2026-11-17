"""Pause and resume preserve the audience and skip uncertain sends."""

import asyncio
from importlib import import_module
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, update

from tests.helpers.factories import create_test_user
from tests.postgres_financial.test_order_intake import command, service
from tests.postgres_financial.test_order_intake import intake_env as _intake_env
from ugc_bot.admin.app import _activate_order, _change_order_dispatch
from ugc_bot.domain.enums import MessengerType, OrderStatus
from ugc_bot.infrastructure.db.messenger_attribution import OFFER_CHANNELS
from ugc_bot.infrastructure.db.models import OrderModel, OutboxEventModel

intake_env = _intake_env  # expose the shared fixture to pytest


@pytest.mark.asyncio
async def test_resume_keeps_audience_and_never_reclaims_unknown(intake_env):
    env = intake_env
    container = env["container"]
    tm = container.transaction_manager
    order_id = (await service(env).create(command(env))).order_id
    async with tm.transaction() as db:
        await db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == order_id)
            .values(
                creator_offer_card={
                    "title": "Ролик для приложения",
                    "task": "Покажи, как пользуешься приложением",
                    "deadline": "В течение недели после согласования",
                    "usage": "Соцсети заказчика",
                }
            )
        )
    ids = [
        (
            await create_test_user(
                env["repos"]["user_repo"],
                external_id=str(uuid4().int % 10**12 + 1),
                country="ru",
            )
        ).user_id
        for _ in range(5)
    ]
    sent, unknown, rejected, unattempted, outsider = ids
    control = env["repos"]["dispatch_control"]

    async def claim(user_id, run):
        async with tm.transaction() as db:
            return await control.claim(order_id, user_id, run, session=db)

    with patch(
        "ugc_bot.admin.app._get_admin_container", return_value=container
    ):
        await _activate_order(order_id, geography_update=(None, None))
        async with tm.transaction() as db:
            assert await control.prepare_audience(
                order_id, ids[:4], 1, session=db
            ) == set(ids[:4])
        assert await claim(sent, 1) == "claimed"
        await container.build_offer_dispatch_service().record_offer_sent(
            order_id, sent
        )
        assert await claim(unknown, 1) == "claimed"
        assert await claim(rejected, 1) == "claimed"
        async with tm.transaction() as db:
            await control.reject(order_id, rejected, 1, session=db)
        assert await claim(rejected, 1) == "skip"

        assert (
            await _change_order_dispatch(order_id, "pause")
            == "Рассылка на паузе."
        )
        assert await claim(unattempted, 1) == "stop"
        assert "поставлено в очередь" in await _change_order_dispatch(
            order_id, "resume"
        )
        assert "недоступно" in await _change_order_dispatch(order_id, "resume")

    async with tm.transaction() as db:
        assert await control.prepare_audience(
            order_id, ids, 2, session=db
        ) == set(ids[:4])
        order = await env["repos"]["order_repo"].get_by_id(order_id, session=db)
        assert order.status == OrderStatus.ACTIVE
        events = (
            await db.scalars(
                select(OutboxEventModel).where(
                    OutboxEventModel.aggregate_id == str(order_id),
                    OutboxEventModel.event_type == "order.activated",
                )
            )
        ).all()
        assert sorted(event.payload["dispatch_run"] for event in events) == [
            1,
            2,
        ]
        publisher = AsyncMock()
        for event in events:
            await container.build_outbox_publisher()._process_order_activation(
                event, publisher, session=db
            )
        assert sorted(
            call.kwargs["dispatch_run"]
            for call in publisher.publish.await_args_list
        ) == [1, 2]

    assert await claim(unattempted, 1) == "stop"
    assert await claim(sent, 2) == "skip"
    assert await claim(unknown, 2) == "skip"
    assert await claim(outsider, 2) == "skip"
    assert await claim(rejected, 2) == "claimed"
    concurrent = await asyncio.gather(
        claim(unattempted, 2), claim(unattempted, 2)
    )
    assert sorted(concurrent) == ["claimed", "skip"]

    async with tm.transaction() as db:
        await db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == order_id)
            .values(status=OrderStatus.CLOSED)
        )
    assert await claim(unknown, 2) == "stop"


@pytest.mark.asyncio
async def test_offer_receipt_binds_callback_and_edit_to_its_own_message(
    intake_env,
):
    env = intake_env
    order_id = (await service(env).create(command(env))).order_id
    creator = await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        country="ru",
    )
    offer_service = env["container"].build_offer_dispatch_service()
    await offer_service.record_offer_sent(
        order_id,
        creator.user_id,
        channel=MessengerType.TELEGRAM,
        message_id="777",
    )
    repo = offer_service.offer_dispatch_repo
    assert await repo.creator_card_matches(
        order_id, creator.user_id, MessengerType.TELEGRAM, "777"
    )
    assert not await repo.creator_card_matches(
        order_id, creator.user_id, MessengerType.MAX, "777"
    )
    assert not await repo.creator_card_matches(
        order_id, creator.user_id, MessengerType.TELEGRAM, "778"
    )
    await repo.mark_creator_card_updated(order_id, creator.user_id, "778")

    async def updated_at():
        tm = env["container"].transaction_manager
        async with tm.transaction() as db:
            return await db.scalar(
                select(OFFER_CHANNELS.c.creator_card_updated_at).where(
                    OFFER_CHANNELS.c.order_id == order_id,
                    OFFER_CHANNELS.c.blogger_id == creator.user_id,
                )
            )

    assert await updated_at() is None
    await repo.mark_creator_card_updated(order_id, creator.user_id, "777")
    first_update = await updated_at()
    assert first_update is not None
    await repo.mark_creator_card_updated(order_id, creator.user_id, "777")
    assert await updated_at() == first_update

    await repo.record_response(order_id, creator.user_id, True, True)
    await offer_service.record_skip(
        order_id, creator.user_id, only_unanswered=True
    )
    (response,) = await repo.list_responses_by_blogger(creator.user_id)
    assert response.accepted and response.in_offer


@pytest.mark.asyncio
async def test_card_migration_preserves_legacy_order_and_receipt_rows(
    intake_env,
):
    env = intake_env
    order_id = (await service(env).create(command(env))).order_id
    order = await env["repos"]["order_repo"].get_by_id(order_id)
    creator = await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        country="ru",
    )
    offer_service = env["container"].build_offer_dispatch_service()
    await offer_service.record_offer_sent(
        order_id, creator.user_id, channel=MessengerType.TELEGRAM
    )
    migration = import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0142_creator_offer_cards"
    )
    with env["pg"].begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            migration.downgrade()
            migration.upgrade()
        after = conn.execute(
            select(
                OrderModel.offer_text,
                OrderModel.price,
                OrderModel.creator_offer_card,
            ).where(OrderModel.order_id == order_id)
        ).one()
        receipt = conn.execute(
            select(
                OFFER_CHANNELS.c.telegram_sent_at,
                OFFER_CHANNELS.c.creator_card_message_id,
            ).where(
                OFFER_CHANNELS.c.order_id == order_id,
                OFFER_CHANNELS.c.blogger_id == creator.user_id,
            )
        ).one()
        assert tuple(after) == (order.offer_text, order.price, None)
        assert receipt.telegram_sent_at is not None
        assert receipt.creator_card_message_id is None
