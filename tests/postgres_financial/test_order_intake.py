"""S01 persists the order, quote, lead and notification intent atomically."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_user,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel


class Clock:
    def __init__(self):
        self.at = datetime.now(timezone.utc)

    def now(self):
        return self.at


@pytest_asyncio.fixture
async def intake_env(financial_pg_engine):
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "KAFKA_ENABLED": False,
            "DATABASE_URL": financial_pg_engine.url.render_as_string(
                hide_password=False
            ),
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
            "FINANCIAL_CORE_ENABLED": True,
            "FINANCIAL_NEW_ORDERS_ENABLED": True,
        }
    )
    container = Container(config)
    repos = container.build_repos()
    user = await create_test_user(
        repos["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        country="ru",
    )
    await create_test_advertiser_profile(repos["advertiser_repo"], user.user_id)
    admin = await create_test_user(
        repos["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        admin=True,
    )
    clock = Clock()
    policy = "intake-" + uuid4().hex
    with Session(financial_pg_engine) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=policy,
                approved_by=admin.user_id,
                approved_at=clock.at - timedelta(days=2),
                effective_from=clock.at - timedelta(days=1),
                refund_window_seconds=3600,
                rules={
                    "terms_reference": "synthetic-approved-terms",
                    "allowed_clients": [str(user.user_id)],
                },
            )
        )
    try:
        yield dict(
            config=config,
            container=container,
            repos=repos,
            user=user,
            admin=admin,
            clock=clock,
            policy=policy,
            pg=financial_pg_engine,
        )
    finally:
        await container.session_factory.kw["bind"].dispose()


def command(env, **changes):
    from ugc_bot.domain.order_intake import OrderIntakeCommand

    return OrderIntakeCommand(
        **(
            dict(
                client_id=env["user"].user_id,
                operation_key="request-" + uuid4().hex,
                policy_version=env["policy"],
                product_link="https://example.test/product",
                offer_text="A real requested brief",
                honorarium=Decimal("999.00"),
                selection_due_at=env["clock"].at + timedelta(days=3),
                contact_reference="client supplied protected contact",
                service_mode="self_service",
            )
            | changes
        )
    )


def service(env, *, repository=None):
    from ugc_bot.application.services.order_intake_service import (
        OrderIntakeService,
    )
    from ugc_bot.infrastructure.db.repositories.order_intake import (
        SqlAlchemyOrderIntakeRepository,
    )

    return OrderIntakeService(
        repository or SqlAlchemyOrderIntakeRepository(),
        env["container"].build_bot_services()["order_service"],
        env["repos"]["financial_policy_repo"],
        env["container"].transaction_manager,
        env["clock"],
        env["config"].financial,
    )


def scoped_rows(env, name, order_id):
    table = Base.metadata.tables[name]
    with Session(env["pg"]) as db:
        return (
            db.execute(select(table).where(table.c.order_id == order_id))
            .mappings()
            .all()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,selected,total,lead_count",
    [
        ("self_service", None, 1500000, 0),
        ("with_manager", None, 5100000, 1),
        ("with_manager", frozenset({1, 7}), 1740000, 1),
    ],
)
async def test_intake_persists_requested_service_and_exact_standard_quote(
    intake_env, mode, selected, total, lead_count
):
    env = intake_env
    request = command(env, service_mode=mode, accompaniment_ordinals=selected)
    result = await service(env).create(request)
    assert result.total_minor == total
    assert result.selection_base_minor == 1500000
    assert result.currency == "RUB"
    assert len(result.items) == 30
    assert {item.selection_minor for item in result.items} == {50000}
    chosen = (
        set()
        if mode == "self_service"
        else (set(range(1, 31)) if selected is None else set(selected))
    )
    assert {
        item.ordinal for item in result.items if item.accompaniment_minor
    } == chosen
    assert {item.accompaniment_minor for item in result.items} <= {0, 120000}
    assert (
        len(scoped_rows(env, "accompaniment_leads", result.order_id))
        == lead_count
    )
    assert (
        len(scoped_rows(env, "accompaniment_lead_outbox", result.order_id))
        == lead_count
    )
    assert len(scoped_rows(env, "order_intake_receipts", result.order_id)) == 1
    assert scoped_rows(env, "financial_obligations", result.order_id) == []
    assert scoped_rows(env, "payments", result.order_id) == []
    order = scoped_rows(env, "orders", result.order_id)[0]
    assert (
        order["price"] == 999
    )  # Direct creator honorarium, outside platform quote.
    if lead_count:
        lead = scoped_rows(env, "accompaniment_leads", result.order_id)[0]
        assert lead["state"] == "requested_unpaid"
        assert lead["client_id"] == env["user"].user_id
        assert lead["contact_reference"] == request.contact_reference
    assert result.honorarium_payment == "paid_direct"


@pytest.mark.asyncio
async def test_same_click_replays_original_ids_dates_without_new_quote(
    intake_env,
):
    env = intake_env
    request = command(env, service_mode="with_manager")
    first = await service(env).create(request)
    env["clock"].at += timedelta(hours=1)
    second = await service(env).create(request)
    assert second == first
    assert len(scoped_rows(env, "order_items", first.order_id)) == 30
    assert len(scoped_rows(env, "accompaniment_leads", first.order_id)) == 1
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await service(env).create(
            replace(request, contact_reference="changed contact")
        )
    assert len(scoped_rows(env, "order_intake_receipts", first.order_id)) == 1


@pytest.mark.asyncio
async def test_commit_failure_rolls_back_order_quote_lead_and_outbox(
    intake_env,
):
    from contextlib import asynccontextmanager

    env = intake_env
    original = env["container"].transaction_manager

    class Failure:
        @asynccontextmanager
        async def transaction(self):
            async with original.transaction() as session:
                yield session
                raise RuntimeError("injected_before_commit")

    intake = service(env)
    intake.transactions = Failure()
    request = command(env, service_mode="with_manager")
    with pytest.raises(RuntimeError, match="injected_before_commit"):
        await intake.create(request)
    with Session(env["pg"]) as db:
        for name in ("orders", "order_intake_receipts", "accompaniment_leads"):
            table = Base.metadata.tables[name]
            field = (
                table.c.advertiser_id if name == "orders" else table.c.client_id
            )
            assert (
                db.execute(
                    select(table).where(field == request.client_id)
                ).first()
                is None
            )


@pytest.mark.asyncio
async def test_disabled_intake_does_not_create_order(intake_env):
    env = intake_env
    env["config"].financial.new_orders_enabled = False
    with pytest.raises(ValueError, match="financial_disabled"):
        await service(env).create(command(env))


@pytest.mark.asyncio
async def test_unapproved_policy_reference_is_not_request_authority(intake_env):
    env = intake_env
    with pytest.raises(ValueError, match="approved_policy_required"):
        await service(env).create(command(env, policy_version="missing-policy"))


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["duplicate_items", "deadline", "terms"])
async def test_intake_receipt_rejects_forged_quote_before_atomic_commit(
    intake_env, tamper
):
    from sqlalchemy.exc import DBAPIError

    from ugc_bot.infrastructure.db.repositories.order_intake import (
        SqlAlchemyOrderIntakeRepository,
    )

    class ForgedReceipt(SqlAlchemyOrderIntakeRepository):
        async def save(self, receipt, lead, *, session):
            result = receipt.result
            changes = {
                "duplicate_items": {"items": (result.items[0],) * 30},
                "deadline": {
                    "selection_due_at": result.selection_due_at
                    + timedelta(days=1)
                },
                "terms": {"terms_reference": "invented-request-approval"},
            }[tamper]
            await super().save(
                replace(receipt, result=replace(result, **changes)),
                lead,
                session=session,
            )

    env = intake_env
    source = command(env, service_mode="with_manager")
    with pytest.raises(DBAPIError, match="intake_quote_mismatch"):
        await service(env, repository=ForgedReceipt()).create(source)
    assert scoped_rows(env, "orders", source.order_id) == []


@pytest.mark.asyncio
async def test_concurrent_same_click_creates_one_order_and_unpaid_lead(
    intake_env,
):
    import asyncio

    env = intake_env
    source = command(env, service_mode="with_manager")
    first, second = await asyncio.gather(
        service(env).create(source), service(env).create(source)
    )
    assert first == second
    for table in (
        "orders",
        "order_intake_receipts",
        "accompaniment_leads",
        "accompaniment_lead_outbox",
    ):
        assert len(scoped_rows(env, table, source.order_id)) == 1


@pytest.mark.asyncio
async def test_non_advertiser_and_missing_user_cannot_create_intake(intake_env):
    env = intake_env
    for identity in (env["admin"].user_id, uuid4()):
        with pytest.raises(PermissionError, match="active_advertiser_required"):
            await service(env).create(command(env, client_id=identity))


@pytest.mark.asyncio
async def test_client_without_published_currency_cannot_create_intake(
    intake_env,
):
    from sqlalchemy import update

    from ugc_bot.infrastructure.db.models import UserModel

    env = intake_env
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["user"].user_id)
            .values(country="unpublished")
        )
    with pytest.raises(ValueError, match="unpublished_currency"):
        await service(env).create(command(env))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table", ["order_intake_receipts", "accompaniment_leads"]
)
async def test_requested_facts_cannot_be_rewritten_or_deleted(
    intake_env, table
):
    from sqlalchemy.exc import DBAPIError

    env = intake_env
    source = command(env, service_mode="with_manager")
    await service(env).create(source)
    for sql in (
        f"DELETE FROM {table} WHERE order_id=:order",
        f"UPDATE {table} SET client_id=:client WHERE order_id=:order",
    ):
        with (
            pytest.raises(DBAPIError, match="order_intake_fact_immutable"),
            Session(env["pg"]) as db,
            db.begin(),
        ):
            db.execute(
                text(sql),
                {"order": source.order_id, "client": env["admin"].user_id},
            )
