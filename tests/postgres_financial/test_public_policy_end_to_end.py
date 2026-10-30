"""Public financial policies keep the whole paid-order lifecycle intact."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.application.services.test_refund_policy_publication import config
from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_user,
)
from tests.postgres_financial.test_checkout_runtime import checkout_env as _env
from tests.postgres_financial.test_client_entitlement_runtime import (
    processor,
    seed_attribution,
)
from tests.postgres_financial.test_order_intake import command, service
from tests.postgres_financial.test_paid_selection_delivery import Bot, Clock
from tests.postgres_financial.test_paid_selection_interest import (
    service as interest_service,
)
from ugc_bot.application.services.checkout_paid_receipts import (
    PaidReceiptProcessor,
)
from ugc_bot.application.services.financial_policy_publication import (
    FinancialPolicyDraft,
    FinancialPolicyPublicationService,
)
from ugc_bot.domain.checkout import CheckoutActor, NativePaidReceipt
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    FinancialPolicyVersionModel,
    OrderItemModel,
    OrderModel,
    OutboxEventModel,
    UserModel,
)


@pytest_asyncio.fixture
async def checkout_env(financial_pg_engine):
    async for env in _env.__wrapped__(financial_pg_engine):
        yield env


@pytest.mark.asyncio
async def test_public_policy_allows_paid_order_and_client_entitlement(
    checkout_env,
):
    env = checkout_env.copy()
    customer = await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        country="ru",
    )
    await create_test_advertiser_profile(
        env["repos"]["advertiser_repo"], customer.user_id
    )
    env["user"] = customer
    env["actor"] = CheckoutActor(
        customer.user_id, "telegram", customer.telegram_id
    )
    client = env["user"].user_id
    assert env["policy"] not in {
        p.version
        for p in (await service(env).eligible_policies(client)).policies
    }
    version = "public-" + uuid4().hex
    draft = FinancialPolicyDraft.from_environment(
        config(),
        version=version,
        effective_from=env["clock"].at,
        allowed_clients=frozenset(),
        all_clients=True,
        terms_reference="terms:synthetic-public",
    )
    policy = await FinancialPolicyPublicationService(
        env["repos"]["financial_policy_repo"],
        env["transactions"],
        env["clock"],
    ).publish(draft, actor_id=env["admin"].user_id)
    assert policy.all_clients
    listed = await service(env).eligible_policies(client)
    assert version in {p.version for p in listed.policies}
    request = command(
        env,
        policy_version=version,
        service_mode="with_manager",
        accompaniment_ordinals=frozenset({1, 7}),
    )
    order = await service(env).create(request)
    assert order.total_minor == 1740000
    worker_env = env | {
        "client": client,
        "order": order.order_id,
        "factory": env["container"].session_factory,
    }
    partner, _ = seed_attribution(worker_env)
    checkout = env["checkout"]
    invoice = await checkout.request_invoice(
        order.order_id, env["actor"], "issue-public"
    )
    assert invoice["invoice_state"] == "ready"
    assert invoice["amount_minor"] == 1740000
    await checkout.authorize(
        order.order_id, env["actor"].external_id, "query-public", 1740000, "RUB"
    )
    receipt = NativePaidReceipt(
        env["actor"].external_id,
        "test-chat",
        "test-message",
        order.order_id,
        "test-provider-charge",
        "test-telegram-charge",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    payment = replace(
        env["container"].build_bot_services()["payment_service"],
        capture_repository=env["checkout_repo"].capture,
        capture_account=env["config"].bot.telegram_payment_account_id,
    )
    paid = PaidReceiptProcessor(
        env["checkout_repo"], env["transactions"], payment
    )
    await paid.accept(receipt)
    assert await paid.run_once()
    status = await checkout.status(order.order_id, env["actor"])
    assert status["capture_state"] == "confirmed"
    await processor(worker_env).process_once()
    with Session(env["pg"]) as db:
        event = db.scalar(
            select(OutboxEventModel).where(
                OutboxEventModel.aggregate_id == str(order.order_id),
                OutboxEventModel.event_type
                == "financial.client_snapshot_requested",
            )
        )
        assert event and event.status == "published", (
            event.last_error if event else None
        )
        obligations = Base.metadata.tables["financial_obligations"]
        rows = (
            db.execute(
                select(obligations).where(
                    obligations.c.order_id == order.order_id
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == 30
        assert all(row["recipient_id"] == partner for row in rows)

    creator = uuid4()
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == order.order_id)
            .values(status=OrderStatus.ACTIVE)
        )
        db.add(
            UserModel(
                user_id=creator,
                telegram_id=str(creator.int % 10**12 + 1),
                messenger_type=MessengerType.TELEGRAM,
                username="synthetic-creator",
                status=UserStatus.ACTIVE,
            )
        )
        db.flush()
        db.add(
            BloggerProfileModel(
                user_id=creator,
                instagram_url="https://instagram.com/" + creator.hex,
                instagram_user_id=creator.hex,
                confirmed=True,
                topics={},
                audience_gender="all",
                audience_age_min=18,
                audience_age_max=40,
                audience_geo="synthetic",
                price=1,
            )
        )
    interest = await interest_service(worker_env).respond(
        order.order_id, creator
    )
    assert interest.accepted and interest.delivery_state == "ready"
    bot = Bot(worker_env)
    delivery = env["container"].build_paid_selection_delivery(bot)
    delivery.clock = Clock()
    await delivery.run_once()
    assert len(bot.calls) == 1
    assert interest.instagram_url in bot.calls[0]["text"]
    with Session(env["pg"]) as db:
        item = db.get(OrderItemModel, interest.paid_item_id)
        assert item.selection_state == "delivered"


@pytest.mark.asyncio
async def test_legacy_pilot_still_rejects_a_client_not_on_its_list(
    checkout_env,
):
    env = checkout_env
    version = "restricted-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=env["admin"].user_id,
                approved_at=env["clock"].at - timedelta(days=2),
                effective_from=env["clock"].at - timedelta(days=1),
                refund_window_seconds=3600,
                rules={
                    "allowed_clients": [str(uuid4())],
                    "terms_reference": "terms:pilot",
                },
            )
        )
    listed = await service(env).eligible_policies(env["user"].user_id)
    assert version not in {p.version for p in listed.policies}
    with pytest.raises(ValueError, match="client_not_allowlisted"):
        await service(env).create(command(env, policy_version=version))
