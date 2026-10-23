from dataclasses import replace

import pytest

from tests.helpers.factories import (
    create_test_advertiser,
    create_test_contact_pricing,
    create_test_order,
)
from tests.helpers.services import build_payment_service
from ugc_bot.application.errors import OrderCreationError
from ugc_bot.domain.enums import OrderStatus


@pytest.mark.asyncio
async def test_payment_replay_after_order_advances(
    fake_tm, user_repo, advertiser_repo, order_repo, payment_repo, pricing_repo
):
    await create_test_contact_pricing(
        pricing_repo, bloggers_count=3, price=1000.0
    )
    user_id = await create_test_advertiser(user_repo, advertiser_repo)
    order = await create_test_order(order_repo, user_id)
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    payment = await service.confirm_telegram_payment(
        user_id, order.order_id, "charge", 100000, "RUB"
    )
    await order_repo.save(replace(order, status=OrderStatus.CLOSED))
    replay = await service.confirm_telegram_payment(
        user_id, order.order_id, "charge", 100000, "RUB"
    )
    assert replay == payment
    assert (
        await order_repo.get_by_id(order.order_id)
    ).status == OrderStatus.CLOSED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"external_id": "different"},
        {"amount": 999.0},
        {"currency": "USD"},
        {"provider": "other"},
    ],
)
async def test_payment_replay_rejects_identity_mismatch(
    fake_tm,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    pricing_repo,
    change,
):
    await create_test_contact_pricing(
        pricing_repo, bloggers_count=3, price=1000.0
    )
    user_id = await create_test_advertiser(user_repo, advertiser_repo)
    order = await create_test_order(order_repo, user_id)
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    payment = await service.confirm_telegram_payment(
        user_id, order.order_id, "charge", 100000, "RUB"
    )
    await payment_repo.save(replace(payment, **change))
    with pytest.raises(OrderCreationError, match="identity"):
        await service.confirm_telegram_payment(
            user_id, order.order_id, "charge", 100000, "RUB"
        )


@pytest.mark.asyncio
async def test_payment_replay_does_not_reprice_after_country_change(
    fake_tm, user_repo, advertiser_repo, order_repo, payment_repo, pricing_repo
):
    await create_test_contact_pricing(
        pricing_repo, bloggers_count=3, price=1000.0
    )
    user_id = await create_test_advertiser(user_repo, advertiser_repo)
    order = await create_test_order(order_repo, user_id)
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    captured = await service.confirm_telegram_payment(
        user_id, order.order_id, "same-captured-charge", 100000, "RUB"
    )
    user = await user_repo.get_by_id(user_id)
    await user_repo.save(replace(user, country="br"))
    await order_repo.save(replace(order, status=OrderStatus.CLOSED))
    replay = await service.confirm_telegram_payment(
        user_id, order.order_id, "same-captured-charge", 100000, "RUB"
    )
    assert replay == captured
    assert (
        await order_repo.get_by_id(order.order_id)
    ).status == OrderStatus.CLOSED
