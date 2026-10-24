"""A delayed real receipt freezes observations at its protocol timestamp."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.postgres_financial.test_client_entitlement_runtime import (
    processor,
    rows,
    seed_attribution,
)
from tests.postgres_financial.test_v1_capture import (
    capture_env as _capture_env,
)
from tests.postgres_financial.test_v1_capture import (
    telegram_receipt,
)
from ugc_bot.application.services.creator_identity_history_service import (
    CreatorIdentityHistoryService,
)
from ugc_bot.domain.enums import PaymentStatus
from ugc_bot.infrastructure.db.models import (
    OutboxEventModel,
    PaymentModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import (
    SqlAlchemyFinancialCaptureRepository,
)
from ugc_bot.infrastructure.db.repositories.identity_history import (
    SqlAlchemyCreatorIdentityHistoryRepository,
)

capture_env = _capture_env


def historical_capture(env):
    prior = env["service"].capture_repository
    repo = SqlAlchemyFinancialCaptureRepository(
        prior.policy_service,
        history=CreatorIdentityHistoryService(
            SqlAlchemyCreatorIdentityHistoryRepository(env["factory"])
        ),
    )
    env["service"].capture_repository = repo
    return repo


async def confirm(env, receipt):
    return await env["service"].confirm_telegram_payment(
        env["client"],
        env["order"],
        receipt.provider_payment_charge_id,
        receipt.total_amount,
        receipt.currency,
        receipt=receipt,
    )


def source(env):
    with Session(env["pg"]) as db:
        return db.scalar(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(env["order"]),
                OutboxEventModel.event_type
                == "financial.client_snapshot_requested",
            )
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_delayed_callback_preserves_original_binding_and_registration(
    request,
):
    env = request.getfixturevalue("capture_env")
    partner, stranger = seed_attribution(env)
    historical_capture(env)
    at = datetime.now(timezone.utc)
    receipt = replace(telegram_receipt(env), protocol_message_at=at)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["client"])
            .values(created_at=at - timedelta(days=730))
        )
        db.execute(
            update(UserReferralBindingModel)
            .where(UserReferralBindingModel.referred_user_id == env["client"])
            .values(referrer_user_id=stranger)
        )
    await confirm(env, receipt)
    stored = source(env)
    assert stored.payload["client_referrer_id"] == str(partner)
    await processor(env).process_once()
    assert {r["recipient_id"] for r in rows(env, "financial_obligations")} == {
        partner
    }
    assert {r["rate_bps"] for r in rows(env, "rate_snapshots")} == {1000}


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_unbound_capture_keeps_known_absence_and_unknown_registration(
    request,
):
    env = request.getfixturevalue("capture_env")
    seed_attribution(env, referred=False)
    historical_capture(env)
    await confirm(
        env,
        replace(
            telegram_receipt(env),
            protocol_message_at=datetime.now(timezone.utc),
        ),
    )
    assert source(env).payload["client_registered_at"] is None
    await processor(env).process_once()
    assert rows(env, "financial_obligations") == []
    assert source(env).status == "published"


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_real_payment_without_history_stays_recorded_but_not_commissioned(
    request,
):
    env = request.getfixturevalue("capture_env")
    seed_attribution(env)
    historical_capture(env)
    payment = await confirm(env, telegram_receipt(env))
    assert payment.status == PaymentStatus.PAID
    stored = source(env)
    assert stored.payload["client_registered_at"] is None
    assert stored.payload["attribution_history"]["status"] == "unavailable"
    with Session(env["pg"]) as db:
        assert db.get(PaymentModel, payment.payment_id).captured_minor == 220000
    await processor(env).process_once()
    assert rows(env, "financial_obligations") == []
    assert source(env).status == "pending"


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_exact_paid_receipt_replay_does_not_require_current_history(
    request,
):
    env = request.getfixturevalue("capture_env")
    seed_attribution(env)
    repo = historical_capture(env)
    receipt = replace(
        telegram_receipt(env), protocol_message_at=datetime.now(timezone.utc)
    )
    paid = await confirm(env, receipt)

    async def unavailable(**kwargs):
        raise AssertionError("paid receipt replay must use original capture")

    repo.history = SimpleNamespace(acquire_snapshot_barrier=unavailable)
    assert (await confirm(env, receipt)).payment_id == paid.payment_id
