"""Only an attempted recipient can bind a callback after a lost receipt."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from tests.helpers.factories import create_test_user
from tests.postgres_financial.test_order_intake import (
    command,
    intake_env,
    service,
)
from ugc_bot.domain.enums import MessengerType, OrderStatus
from ugc_bot.infrastructure.db.messenger_attribution import OFFER_CHANNELS
from ugc_bot.infrastructure.db.models import OfferDispatchModel

__all__ = ["intake_env"]


@pytest_asyncio.fixture
async def claimed_card(intake_env):
    env = intake_env
    repos = env["repos"]
    receipt = await service(env).create(command(env))
    creator = await create_test_user(
        repos["user_repo"], external_id=str(uuid4().int % 10**12 + 1)
    )
    tm = env["container"].transaction_manager
    control = repos["dispatch_control"]
    async with tm.transaction() as db:
        order = await repos["order_repo"].get_by_id(
            receipt.order_id, session=db
        )
        await repos["order_repo"].save(
            replace(
                order,
                status=OrderStatus.ACTIVE,
                creator_offer_card={
                    "title": "Technical card",
                    "task": "Record a video",
                    "deadline": "One week",
                    "usage": "Social media",
                },
            ),
            session=db,
        )
        assert await control.start(receipt.order_id, session=db) == 1
        assert await control.prepare_audience(
            receipt.order_id, [creator.user_id], 1, session=db
        ) == {creator.user_id}
    return env | {"order_id": receipt.order_id, "creator": creator}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode, expected",
    [
        ("claimed", True),
        ("resumed", True),
        ("unattempted", False),
        ("rejected", False),
        ("outsider", False),
        ("legacy", False),
        ("already_bound", False),
        ("missing_message_id", True),
        ("missing_order", False),
        ("other_channel", False),
    ],
)
async def test_callback_recovery_preserves_recipient_and_message_scope(
    claimed_card, mode, expected
):
    env = claimed_card
    container = env["container"]
    tm = container.transaction_manager
    repos = env["repos"]
    control = repos["dispatch_control"]
    order_id, creator = env["order_id"], env["creator"].user_id
    async with tm.transaction() as db:
        if mode != "unattempted":
            assert (
                await control.claim(order_id, creator, 1, session=db)
                == "claimed"
            )
        if mode == "rejected":
            await control.reject(order_id, creator, 1, session=db)
        if mode == "resumed":
            assert await control.change(order_id, paused=True, session=db) == 1
            assert await control.change(order_id, paused=False, session=db) == 2
        if mode == "legacy":
            order = await repos["order_repo"].get_by_id(order_id, session=db)
            await repos["order_repo"].save(
                replace(order, creator_offer_card=None), session=db
            )
    repo = repos["offer_dispatch_repo"]
    if mode in {"already_bound", "missing_message_id", "other_channel"}:
        await repo.record_sent(
            order_id,
            creator,
            channel=MessengerType.TELEGRAM,
            message_id=None if mode == "missing_message_id" else "901",
        )
    recipient = env["user"].user_id if mode == "outsider" else creator
    request_order = uuid4() if mode == "missing_order" else order_id
    channel = (
        MessengerType.MAX if mode == "other_channel" else MessengerType.TELEGRAM
    )
    message_id = "901" if mode == "other_channel" else "902"
    assert (
        await repo.recover_creator_card_receipt(
            request_order, recipient, channel, message_id
        )
        is expected
    )
    async with tm.transaction() as db:
        recorded = (
            (
                await db.execute(
                    select(OFFER_CHANNELS.c.creator_card_message_id).where(
                        OFFER_CHANNELS.c.order_id == order_id
                    )
                )
            )
            .scalars()
            .all()
        )
    expected_messages = {
        "claimed": ["902"],
        "resumed": ["902"],
        "already_bound": ["901"],
        "missing_message_id": ["902"],
        "other_channel": ["901"],
    }
    assert recorded == expected_messages.get(mode, [])


@pytest.mark.asyncio
@pytest.mark.parametrize("second_message", ["902", "903"])
async def test_concurrent_callbacks_bind_one_message(
    claimed_card, second_message
):
    env = claimed_card
    tm = env["container"].transaction_manager
    order_id, creator = env["order_id"], env["creator"].user_id
    async with tm.transaction() as db:
        assert (
            await env["repos"]["dispatch_control"].claim(
                order_id, creator, 1, session=db
            )
            == "claimed"
        )
    repo = env["repos"]["offer_dispatch_repo"]
    results = await asyncio.gather(
        repo.recover_creator_card_receipt(
            order_id, creator, MessengerType.TELEGRAM, "902"
        ),
        repo.recover_creator_card_receipt(
            order_id, creator, MessengerType.TELEGRAM, second_message
        ),
    )
    assert sorted(results) == (
        [True, True] if second_message == "902" else [False, True]
    )
    async with tm.transaction() as db:
        dispatches = list(
            await db.scalars(
                select(OfferDispatchModel).where(
                    OfferDispatchModel.order_id == order_id
                )
            )
        )
        assert len(dispatches) == 1 and dispatches[0].accepted is None


@pytest.mark.asyncio
async def test_send_acknowledgement_and_callback_share_the_same_lock(
    claimed_card,
):
    env = claimed_card
    order_id, creator = env["order_id"], env["creator"].user_id
    async with env["container"].transaction_manager.transaction() as db:
        assert (
            await env["repos"]["dispatch_control"].claim(
                order_id, creator, 1, session=db
            )
            == "claimed"
        )
    repo = env["repos"]["offer_dispatch_repo"]
    _, recovered = await asyncio.wait_for(
        asyncio.gather(
            repo.record_sent(
                order_id,
                creator,
                channel=MessengerType.TELEGRAM,
                message_id="902",
            ),
            repo.recover_creator_card_receipt(
                order_id, creator, MessengerType.TELEGRAM, "902"
            ),
        ),
        timeout=3,
    )
    assert recovered
    assert await repo.creator_card_matches(
        order_id, creator, MessengerType.TELEGRAM, "902"
    )
