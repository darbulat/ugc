"""Real paid 10 + reserve handoffs, without new paid positions or movements."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.postgres_financial.test_creator_social import seed_profile
from tests.postgres_financial.test_order_intake import intake_env
from tests.postgres_financial.test_telegram_order_summary import paid_order
from ugc_bot.admin.creator_transfers import transfer_activity
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.application.services.creator_transfer_service import (
    CreatorTransferService,
)
from ugc_bot.domain.enums import OrderStatus, RaterRole
from ugc_bot.infrastructure.db.creator_transfer_models import TRANSFERS
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    FinancialMovementModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.creator_transfers import (
    SqlCreatorTransfers,
    delivered_count,
    delivery_history,
)
from ugc_bot.infrastructure.db.selection_delivery_models import ACCEPTED

__all__ = ["intake_env"]


def contact_profile(db, **kwargs):
    cid = seed_profile(db, **kwargs)
    db.execute(
        update(BloggerProfileModel)
        .where(BloggerProfileModel.user_id == cid)
        .values(instagram_url=f"https://instagram.com/u{cid.hex[:28]}/")
    )
    return cid


async def setup(env, *, size=10, reserve=1, closed=False):
    summary, oid, interests, principal, _ = await paid_order(
        env,
        size=size,
        interested_creators=size + reserve,
        creator_factory=contact_profile,
    )
    candidates = [row.creator_id for row in interests if not row.accepted]
    with Session(env["pg"]) as db, db.begin():
        if closed:
            db.execute(
                update(OrderModel)
                .where(OrderModel.order_id == oid)
                .values(status=OrderStatus.CLOSED)
            )
        baseline = db.scalar(
            select(func.count()).select_from(FinancialMovementModel)
        )
    receipts = iter(range(1, 100))
    transport = SimpleNamespace(
        send=AsyncMock(
            side_effect=lambda m: DeliveryReceipt(
                "telegram", f"{m.address}:extra-{next(receipts)}"
            )
        )
    )
    service = CreatorTransferService(
        SqlCreatorTransfers(),
        env["container"].transaction_manager,
        transport,
        env["clock"],
    )
    return service, transport, oid, candidates, summary, principal, baseline


@pytest.mark.asyncio
@pytest.mark.parametrize("closed", [False, True])
async def test_manual_delivery_keeps_history_and_can_reach_twenty_of_ten(
    intake_env, closed
):
    env = intake_env
    (
        service,
        transport,
        oid,
        candidates,
        summary,
        principal,
        baseline,
    ) = await setup(env, reserve=10, closed=closed)
    for cid in candidates:
        assert (
            await service.send(oid, cid, operator="admin:synthetic") == "sent"
        )
    for cid in candidates:
        assert (
            await service.send(oid, cid, operator="admin:synthetic") == "sent"
        )
    assert transport.send.await_count == 10
    async with service.transactions.transaction() as db:
        assert await delivered_count(db, oid) == 20
        history = await delivery_history(db, oid)
        assert len(history) == 20
        assert len({row["creator_id"] for row in history}) == 20
        assert all(row["contact"]["instagram"] for row in history)
        assert all(
            "attempt_token" not in row and "operator" not in row
            for row in history
        )
        activity = await transfer_activity(db, oid)
        assert activity["count"] == 20 and activity["needed"] == 10
        assert len(activity["candidates"]) == 10
        assert all(row["state"] == "sent" for row in activity["candidates"])
        assert activity["can_send"] is True
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(OrderItemModel)
                .where(OrderItemModel.order_id == oid)
            )
            == 10
        )
        assert (
            db.scalar(select(func.count()).select_from(FinancialMovementModel))
            == baseline
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(OrderItemModel)
                .where(OrderItemModel.order_id == oid)
            )
            == 10
        )
        assert db.get(OrderModel, oid).status == (
            OrderStatus.CLOSED if closed else OrderStatus.ACTIVE
        )
    data = await summary.view(principal, oid)
    assert data["transferred"] == 20 and data["requested"] == 10
    view = (
        await env["container"]
        .build_bot_services()["selection_view_service"]
        .view(oid, principal.user_id, principal=principal)
    )
    assert len(view["delivered_authors"]) == 20
    ratings = env["container"].build_bot_services()["blogger_rating_service"]
    assert (
        len(
            await ratings.list_for_order(
                principal.user_id, oid, principal=principal
            )
        )
        == 20
    )


@pytest.mark.asyncio
async def test_counteroffer_is_sent_only_manually_and_counts_once(intake_env):
    env = intake_env
    service, transport, oid, _, _, _, baseline = await setup(env)
    with env["pg"].begin() as db:
        cid = contact_profile(db, stable_id=uuid4().hex)
        db.execute(
            OfferDispatchModel.__table__.insert().values(
                order_id=oid,
                blogger_id=cid,
                accepted=False,
                in_offer=False,
                desired_price=Decimal("3500"),
                rejection_reason="low_price",
            )
        )
    assert transport.send.await_count == 0
    await asyncio.gather(
        *(service.send(oid, cid, operator="admin:synthetic") for _ in range(4))
    )
    assert transport.send.await_count == 1
    assert "3 500 ₽" in transport.send.call_args.args[0].text
    assert "Цена требует согласования" in transport.send.call_args.args[0].text
    async with service.transactions.transaction() as db:
        assert await delivered_count(db, oid) == 11
        activity = await transfer_activity(db, oid)
        forwarded = next(
            row for row in activity["candidates"] if row["creator_id"] == cid
        )
        assert forwarded["source"] == "Новая цена"
        assert forwarded["price"] == Decimal("3500")
        assert forwarded["state"] == "sent"
    with Session(env["pg"]) as db:
        assert (
            db.scalar(select(func.count()).select_from(FinancialMovementModel))
            == baseline
        )
        offer = db.get(OfferDispatchModel, (oid, cid))
        assert offer.accepted is False and offer.in_offer is False


@pytest.mark.asyncio
async def test_failure_unknown_and_expired_attempt_do_not_duplicate(intake_env):
    env = intake_env
    service, transport, oid, candidates, _, _, _ = await setup(env)
    cid = candidates[0]
    transport.send.side_effect = DeliveryFailure("blocked", uncertain=False)
    assert await service.send(oid, cid, operator="admin:synthetic") == "failed"
    async with service.transactions.transaction() as db:
        assert await delivered_count(db, oid) == 10
        activity = await transfer_activity(db, oid)
        assert activity["count"] == 10
        assert activity["candidates"][0]["state"] == "failed"
    transport.send.side_effect = TimeoutError()
    assert await service.send(oid, cid, operator="admin:synthetic") == "unknown"
    assert await service.send(oid, cid, operator="admin:synthetic") == "unknown"
    assert transport.send.await_count == 2
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(TRANSFERS)
            .where(TRANSFERS.c.order_id == oid)
            .values(
                state="sending",
                started_at=env["clock"].at - timedelta(minutes=3),
            )
        )
    assert await service.send(oid, cid, operator="admin:synthetic") == "unknown"
    assert transport.send.await_count == 2


@pytest.mark.asyncio
async def test_feedback_for_extra_author_is_owner_scoped_and_not_billing(
    intake_env,
):
    env = intake_env
    service, _, oid, candidates, _, principal, baseline = await setup(
        env, closed=True
    )
    cid = candidates[0]
    await service.send(oid, cid, operator="admin:synthetic")
    ratings = env["container"].build_bot_services()["blogger_rating_service"]
    with pytest.raises(ValueError, match="rating_work_incomplete"):
        await ratings.rate_blogger(
            cid,
            oid,
            principal.user_id,
            RaterRole.ADVERTISER,
            5,
            principal=principal,
        )
    outsider = env["admin"]
    foreign = AuthenticatedMessengerPrincipal(
        outsider.user_id, "telegram", outsider.telegram_id
    )
    with pytest.raises(ValueError, match="rating_access_denied"):
        await ratings.record_supplemental_feedback(
            outsider.user_id, oid, cid, "worked", principal=foreign
        )
    await ratings.record_supplemental_feedback(
        principal.user_id, oid, cid, "not_agreed", principal=principal
    )
    assert not next(
        row
        for row in await ratings.list_for_order(
            principal.user_id, oid, principal=principal
        )
        if row["blogger_id"] == str(cid)
    )["rating_eligible"]
    await ratings.record_supplemental_feedback(
        principal.user_id, oid, cid, "worked", principal=principal
    )
    await ratings.rate_blogger(
        cid,
        oid,
        principal.user_id,
        RaterRole.ADVERTISER,
        5,
        principal=principal,
    )
    with Session(env["pg"]) as db:
        assert (
            db.scalar(select(func.count()).select_from(FinancialMovementModel))
            == baseline
        )
    with pytest.raises(IntegrityError), env["pg"].begin() as db:
        db.execute(
            update(TRANSFERS)
            .where(TRANSFERS.c.order_id == oid)
            .values(contact={})
        )
    with pytest.raises(IntegrityError), env["pg"].begin() as db:
        db.execute(TRANSFERS.delete().where(TRANSFERS.c.order_id == oid))


@pytest.mark.asyncio
async def test_rejected_sources_never_start_a_transfer(intake_env):
    env = intake_env
    service, transport, oid, candidates, _, _, _ = await setup(env)
    cid = candidates[0]
    with pytest.raises(ValueError, match="transfer_order_unavailable"):
        await service.send(uuid4(), cid, operator="admin:synthetic")
    with env["pg"].begin() as db:
        unrelated = contact_profile(db, stable_id=uuid4().hex)
        original = db.scalar(
            select(ACCEPTED.c.creator_id)
            .where(ACCEPTED.c.order_id == oid)
            .limit(1)
        )
    assert (
        await service.send(oid, original, operator="admin:synthetic") == "sent"
    )
    with pytest.raises(ValueError, match="transfer_candidate_required"):
        await service.send(oid, unrelated, operator="admin:synthetic")
    with env["pg"].begin() as db:
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == cid)
            .values(status="pause")
        )
    with pytest.raises(ValueError, match="transfer_creator_unavailable"):
        await service.send(oid, cid, operator="admin:synthetic")
    with env["pg"].begin() as db:
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == cid)
            .values(status="active")
        )
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["user"].user_id)
            .values(telegram_id=None)
        )
    with pytest.raises(ValueError, match="transfer_customer_unavailable"):
        await service.send(oid, cid, operator="admin:synthetic")
    transport.send.assert_not_awaited()
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(TRANSFERS)
                .where(TRANSFERS.c.order_id == oid)
            )
            == 0
        )
