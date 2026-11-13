"""Exercise cancellation and native authorization on migrated PostgreSQL."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.helpers.factories import create_test_order
from tests.postgres_financial.test_checkout_runtime import (
    checkout_env as checkout_env,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.container.customer_workflow_factory import build_customer_workflows
from ugc_bot.domain.customer_workflows import SupportInput
from ugc_bot.domain.enums import OrderStatus, PaymentStatus
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    OfferDispatchModel,
    PaymentModel,
)

__all__ = ["checkout_env"]


def services(env):
    return build_customer_workflows(env["transactions"], env["clock"])


def principal(env):
    return AuthenticatedMessengerPrincipal(
        env["user"].user_id, "telegram", env["actor"].external_id
    )


async def cancel(env, *, confirm=True):
    return await services(env)["order_cancellation_service"].cancel(
        env["user"].user_id,
        env["order"].order_id,
        principal=principal(env),
        confirm=confirm,
    )


async def authorize(env):
    return await env["checkout"].authorize(
        env["order"].order_id,
        env["actor"].external_id,
        "native-query",
        1740000,
        "RUB",
    )


@pytest.mark.asyncio
async def test_cancellation_with_issued_invoice_is_idempotent(checkout_env):
    env = checkout_env
    oid = env["order"].order_id
    await env["checkout"].request_invoice(oid, env["actor"], "issue")
    assert await cancel(env, confirm=False) == "confirm"
    with pytest.raises(ValueError, match="financial_principal_changed"):
        await services(env)["order_cancellation_service"].cancel(
            env["user"].user_id,
            oid,
            principal=replace(principal(env), external_id="someone-else"),
            confirm=True,
        )
    assert await asyncio.gather(cancel(env), cancel(env)) == ["cancelled"] * 2
    assert await services(env)["order_cancellation_service"].cancelled_orders(
        [oid, uuid4()]
    ) == {oid}
    assert (
        await env["repos"]["order_repo"].get_by_id(oid)
    ).status == OrderStatus.CLOSED
    with pytest.raises(ValueError):
        await authorize(env)
    replay = await env["checkout"].request_invoice(oid, env["actor"], "issue")
    assert replay["can_open"] is False and replay["invoice_url"] is None
    with Session(env["pg"]) as db:
        payment = db.scalar(
            select(PaymentModel).where(PaymentModel.order_id == oid)
        )
        assert (
            payment.status == PaymentStatus.PENDING
            and payment.captured_minor is None
        )
        audit = db.scalars(
            select(AuditLogModel).where(AuditLogModel.entity_id == oid)
        ).one()
        assert audit.changed_by == env["user"].user_id


@pytest.mark.asyncio
async def test_native_authorization_and_cancel_cannot_both_win(checkout_env):
    env = checkout_env
    oid = env["order"].order_id
    await env["checkout"].request_invoice(oid, env["actor"], "issue")
    result, auth = await asyncio.gather(
        cancel(env), authorize(env), return_exceptions=True
    )
    assert result in {"cancelled", "processing"}
    if result == "cancelled":
        assert isinstance(auth, ValueError)
        expected_state = "unpaid"
    else:
        assert auth["order_id"] == oid
        expected_state = "processing"
    command = SupportInput(
        order_id=oid,
        operation_key="payment-help",
        reason="The payment screen stopped.",
        contact_reference="telegram:synthetic",
    )
    support = services(env)["order_support_service"]
    request = await support.create_payment_request(
        env["user"].user_id, command, principal=principal(env)
    )
    replay = await support.create_payment_request(
        env["user"].user_id, command, principal=principal(env)
    )
    assert request["request_id"] == replay["request_id"]
    assert request["payload"]["topic"] == "payment"
    assert request["payload"]["payment_state"] == expected_state


@pytest.mark.asyncio
async def test_legacy_payment_in_flight_and_active_orders_are_preserved(
    checkout_env,
):
    env = checkout_env
    user_id = env["user"].user_id
    orders = env["repos"]["order_repo"]
    legacy = await create_test_order(orders, advertiser_id=user_id)
    active = await create_test_order(
        orders, advertiser_id=user_id, status=OrderStatus.ACTIVE
    )
    cancellable = await create_test_order(orders, advertiser_id=user_id)
    previously_dispatched = await create_test_order(
        orders, advertiser_id=user_id
    )
    with Session(env["pg"]) as db, db.begin():
        db.add(
            PaymentModel(
                order_id=legacy.order_id,
                status=PaymentStatus.PENDING,
                provider="synthetic",
                amount=1,
                currency="RUB",
                external_id="precheckout:synthetic",
            )
        )
        db.add(
            OfferDispatchModel(
                order_id=previously_dispatched.order_id,
                blogger_id=env["admin"].user_id,
                in_offer=True,
                created_at=env["clock"].at,
            )
        )
    for order, expected in [
        (legacy, "processing"),
        (active, "unavailable"),
        (previously_dispatched, "unavailable"),
        (cancellable, "cancelled"),
    ]:
        assert await cancel(env | {"order": order}) == expected
    assert (await orders.get_by_id(legacy.order_id)).status == OrderStatus.NEW
    assert (
        await orders.get_by_id(active.order_id)
    ).status == OrderStatus.ACTIVE
