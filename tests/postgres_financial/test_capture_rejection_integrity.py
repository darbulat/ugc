"""Persisted rejection invariants for existing Task16 defensive branches."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.postgres_financial import test_v1_capture as capture_tests
from ugc_bot.application.errors import OrderCreationError
from ugc_bot.domain.enums import OrderStatus, PaymentStatus
from ugc_bot.infrastructure.db.models import (
    OrderItemModel,
    OrderModel,
    OutboxEventModel,
    PaymentItemAllocationModel,
    PaymentModel,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import intent_id

capture_env = capture_tests.capture_env


def assert_pending_intact(env):
    with Session(env["pg"]) as db:
        order = db.get(OrderModel, env["order"])
        assert order is not None and order.status == OrderStatus.NEW
        payment = db.scalars(
            select(PaymentModel).where(PaymentModel.order_id == env["order"])
        ).one()
        assert payment.status == PaymentStatus.PENDING
        assert payment.captured_minor in (None, 0)
        items = db.scalars(
            select(OrderItemModel).where(
                OrderItemModel.order_id == env["order"]
            )
        ).all()
        assert len(items) == 2
        assert all(item.captured_at is None for item in items)
        intent = db.get(OutboxEventModel, intent_id(env["order"]))
        assert intent is not None
        assert intent.payload["account"] == "test-merchant"
        assert intent.payload["client_id"] == str(env["client"])
        assert intent.payload["policy_version"] == env["version"]
        assert (
            db.scalar(
                select(func.count())
                .select_from(PaymentItemAllocationModel)
                .where(PaymentItemAllocationModel.order_id == env["order"])
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(
                    OutboxEventModel.aggregate_id == str(env["order"]),
                    OutboxEventModel.event_type
                    == "financial.client_snapshot_requested",
                )
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_time", ["after_due", "naive"])
async def test_invalid_protocol_time_leaves_pending_money_untouched(
    capture_env, invalid_time
):
    env = capture_env
    receipt = capture_tests.telegram_receipt(env)
    at = (
        env["now"] + timedelta(days=4)
        if invalid_time == "after_due"
        else receipt.protocol_message_at.replace(tzinfo=None)
    )
    receipt = replace(receipt, protocol_message_at=at)
    message = (
        "invalid_capture_policy"
        if invalid_time == "after_due"
        else "trusted_protocol_time_required"
    )
    with pytest.raises(OrderCreationError, match=message):
        await env["service"].confirm_telegram_payment(
            env["client"],
            env["order"],
            receipt.provider_payment_charge_id,
            receipt.total_amount,
            receipt.currency,
            receipt=receipt,
        )
    assert_pending_intact(env)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,reason",
    [
        ("owner", "capture_order_owner_mismatch"),
        ("empty_account", "capture_account_required"),
        ("changed_account", "capture_intent_conflict"),
    ],
)
async def test_rejected_invoice_retry_preserves_original_intent(
    capture_env, case, reason
):
    env = capture_env
    service = env["service"]
    client = uuid4() if case == "owner" else env["client"]
    account = {
        "owner": service.capture_account,
        "empty_account": " ",
        "changed_account": "another-synthetic-account",
    }[case]
    with pytest.raises(OrderCreationError, match=reason):
        async with env["factory"].begin() as session:
            await service.capture_repository.issue(
                env["order"], client, account, session=session
            )
    assert_pending_intact(env)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_v1,reason",
    [(False, "financial_order_required"), (True, "approved_quote_required")],
)
async def test_order_without_financial_quote_cannot_issue(
    capture_env, is_v1, reason
):
    env = capture_env
    order_id = uuid4()
    with Session(env["pg"]) as db, db.begin():
        db.add(
            OrderModel(
                order_id=order_id,
                advertiser_id=env["client"],
                product_link="synthetic",
                offer_text="synthetic",
                price=1,
                bloggers_needed=2,
                status=OrderStatus.NEW,
                created_at=env["now"],
                financial_version=env["version"] if is_v1 else None,
            )
        )
    with pytest.raises(OrderCreationError, match=reason):
        async with env["factory"].begin() as session:
            await env["service"].capture_repository.issue(
                order_id, env["client"], "test-merchant", session=session
            )
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(PaymentModel)
                .where(PaymentModel.order_id == order_id)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.aggregate_id == str(order_id))
            )
            == 0
        )
    assert_pending_intact(env)
