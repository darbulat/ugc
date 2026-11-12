"""Pause and resume preserve the audience and skip uncertain sends."""

import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from tests.helpers.factories import create_test_user
from tests.postgres_financial.test_order_intake import command, service
from tests.postgres_financial.test_order_intake import intake_env as _intake_env
from ugc_bot.admin.app import _activate_order, _change_order_dispatch
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.models import OrderModel, OutboxEventModel

intake_env = _intake_env  # expose the shared fixture to pytest


@pytest.mark.asyncio
async def test_resume_keeps_audience_and_never_reclaims_unknown(intake_env):
    env = intake_env
    container = env["container"]
    tm = container.transaction_manager
    order_id = (await service(env).create(command(env))).order_id
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
