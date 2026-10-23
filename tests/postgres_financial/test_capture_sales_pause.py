"""Already issued invoices survive a sales pause, without toggling gates."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.postgres_financial import test_v1_capture as capture_tests
from ugc_bot.infrastructure.db.models import (
    OutboxEventModel,
    PaymentItemAllocationModel,
    PaymentModel,
)

capture_env = capture_tests.capture_env


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "core,new_orders", [(True, False), (False, False), (False, True)]
)
async def test_issued_capture_survives_pause(capture_env, core, new_orders):
    env = capture_env
    service = env["service"]
    config = service.capture_repository.policy_service.config
    # The fixture committed a synthetic invoice intent while enabled.
    config.core_enabled = core
    config.new_orders_enabled = new_orders
    receipt = capture_tests.telegram_receipt(env)
    payment = await service.confirm_telegram_payment(
        env["client"],
        env["order"],
        receipt.provider_payment_charge_id,
        receipt.total_amount,
        receipt.currency,
        receipt=receipt,
    )
    assert (config.core_enabled, config.new_orders_enabled) == (
        core,
        new_orders,
    )
    with Session(env["pg"]) as db:
        persisted = db.get(PaymentModel, payment.payment_id)
        assert persisted is not None
        assert persisted.captured_minor == receipt.total_amount
        allocated = db.scalar(
            select(func.sum(PaymentItemAllocationModel.amount_minor)).where(
                PaymentItemAllocationModel.payment_id == payment.payment_id
            )
        )
        assert allocated == receipt.total_amount
        requests = db.scalar(
            select(func.count())
            .select_from(OutboxEventModel)
            .where(
                OutboxEventModel.aggregate_id == str(env["order"]),
                OutboxEventModel.event_type
                == "financial.client_snapshot_requested",
            )
        )
        assert requests == 1
