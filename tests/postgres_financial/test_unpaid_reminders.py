"""Payment reminder acceptance on isolated PostgreSQL and synthetic users."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from ugc_bot import unpaid_reminder_scheduler as scheduler
from ugc_bot.application.notice_delivery_ports import DeliveryFailure
from ugc_bot.config import load_config
from ugc_bot.domain.enums import AuditAction, OrderStatus, PaymentStatus
from ugc_bot.infrastructure.db.customer_workflow_models import JOBS, SERIES
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    OrderModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.reminder_coordination import ORDER_REMINDER
from ugc_bot.infrastructure.db.repositories import unpaid_reminders as repo
from ugc_bot.infrastructure.db.repositories.customer_workflows import (
    SqlAlchemyCustomerWorkflowRepository,
)
from ugc_bot.infrastructure.db.session import (
    SessionTransactionManager,
    create_session_factory,
)
from ugc_bot.infrastructure.messenger.notice_receipts import (
    TelegramNoticeReceipts,
)

AT = datetime(2026, 11, 13, 9, tzinfo=timezone.utc)
START = AT - timedelta(days=7)


def seed(engine):
    with Session(engine) as session, session.begin():
        ids = {}
        for address, case, age in [
            ("11101", "older", 50),
            ("11101", "latest", 30),
            ("11102", "ambiguous", 28),
            ("11103", "payment_pending", 40),
            ("11104", "test", 33),
            ("11105", "hidden", 35),
            ("11106", "pre_launch", 240),
            ("11107", "fresh", 12),
            ("11108", "excluded", 29),
            ("11109", "opted_out", 27),
            ("11110", "followup_today", 26),
        ]:
            user = session.scalar(
                select(UserModel).where(UserModel.telegram_id == address)
            )
            if user is None:
                user = UserModel(
                    user_id=uuid4(),
                    username=f"fixture-{address}",
                    telegram_id=address,
                    messenger_type="telegram",
                    status="active",
                    role_chosen_at=AT,
                )
                session.add(user)
                session.flush()
                session.add(
                    AdvertiserProfileModel(
                        user_id=user.user_id, contact="fixture", brand=case
                    )
                )
            order_id = uuid4()
            session.add(
                OrderModel(
                    order_id=order_id,
                    advertiser_id=user.user_id,
                    status=OrderStatus.NEW,
                    offer_text=case,
                    product_link="https://example.invalid",
                    price=1000,
                    bloggers_needed=3,
                    created_at=AT - timedelta(hours=age),
                )
            )
            session.flush()
            if case == "payment_pending":
                session.add(
                    PaymentModel(
                        payment_id=uuid4(),
                        order_id=order_id,
                        status=PaymentStatus.PENDING,
                        amount=1000,
                        currency="RUB",
                        provider="fixture",
                        external_id="pending",
                    )
                )
            if case in {"opted_out", "followup_today"}:
                series_id = uuid4()
                session.execute(
                    insert(SERIES).values(
                        series_id=series_id,
                        user_id=user.user_id,
                        generation=1,
                        created_at=AT - timedelta(days=2),
                        last_activity_at=AT,
                        order_id=order_id,
                        channel="telegram",
                        opted_out=case == "opted_out",
                    )
                )
                if case == "followup_today":
                    session.execute(
                        insert(JOBS).values(
                            job_id=uuid4(),
                            series_id=series_id,
                            recipient_id=user.user_id,
                            stage=1,
                            generation=1,
                            due_at=AT,
                            state="accepted",
                            lease_until=AT,
                            provider_reference="synthetic",
                        )
                    )
            if case in {"test", "hidden"}:
                entity, values = (
                    ("order_test_marker", {"test": True})
                    if case == "test"
                    else ("order_worklist_visibility", {"visible": False})
                )
                session.add(
                    AuditLogModel(
                        entity_type=entity,
                        entity_id=order_id,
                        action=AuditAction.UPDATE,
                        new_values=values,
                    )
                )
            ids[case] = (order_id, user.user_id)
        return ids


@pytest.mark.asyncio
async def test_unpaid_reminders_use_test_accounts_without_duplicate_attempts(
    financial_pg_engine, monkeypatch
):
    ids = seed(financial_pg_engine)
    factory = create_session_factory(
        financial_pg_engine.url.render_as_string(hide_password=False)
    )
    transactions = SessionTransactionManager(factory)
    container = SimpleNamespace(transaction_manager=transactions)
    monkeypatch.setattr(
        scheduler, "datetime", SimpleNamespace(now=lambda zone: AT)
    )
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "test_only_bot")
    monkeypatch.setenv("UNPAID_REMINDERS_ENABLED", "false")
    monkeypatch.setenv("UNPAID_REMINDERS_START_AT", START.isoformat())
    monkeypatch.setenv(
        "UNPAID_REMINDERS_EXCLUDED_USERS", f'["{ids["excluded"][1]}"]'
    )
    config = load_config()

    async def send(**request):
        assert request["chat_id"] in {11101, 11102}
        if request["chat_id"] == 11102:
            raise DeliveryFailure("synthetic_uncertain", uncertain=True)
        button = request["reply_markup"].inline_keyboard[0][0]
        assert (
            button.url
            == f"https://t.me/test_only_bot?start=pay_{ids['latest'][0]}"
        )
        return SimpleNamespace(message_id=7, chat=SimpleNamespace(id=11101))

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=send))
    transport = TelegramNoticeReceipts(bot, use_web_app=False)
    assert await scheduler.run_once(config, container, transport) == 0
    bot.send_message.assert_not_awaited()
    monkeypatch.setenv(
        "DATABASE_URL",
        financial_pg_engine.url.render_as_string(hide_password=False),
    )
    config = load_config()
    report = await scheduler.preview(config, START, AT)
    assert report["count"] == 2 and report["send_window"]
    with Session(financial_pg_engine) as session:
        assert (
            session.scalar(
                select(func.count()).where(
                    AuditLogModel.entity_type == ORDER_REMINDER
                )
            )
            == 0
        )
    async with transactions.transaction() as session:
        candidates = await repo.list_candidates(
            session, AT, START, config.order.unpaid_reminders_excluded_users
        )
        assert {row[0].order_id for row in candidates} == {
            ids["latest"][0],
            ids["ambiguous"][0],
        }
    config.order.unpaid_reminders_enabled = True
    assert (
        sum(
            await asyncio.gather(
                *(
                    scheduler.run_once(config, container, transport)
                    for _ in range(2)
                )
            )
        )
        == 2
    )
    assert bot.send_message.await_count == 2
    assert await scheduler.run_once(config, container, transport) == 0
    async with transactions.transaction() as session:
        later = await repo.list_candidates(
            session,
            AT + timedelta(hours=25),
            START,
            config.order.unpaid_reminders_excluded_users,
        )
        assert ids["older"][0] not in {row[0].order_id for row in later}
    with Session(financial_pg_engine) as session:
        statuses = repo.reminder_statuses(
            session, [pair[0] for pair in ids.values()]
        )
        assert {key: value[0] for key, value in statuses.items()} == {
            ids["latest"][0]: "accepted",
            ids["ambiguous"][0]: "unknown",
        }
    await factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_payment_reminder_defers_existing_followup(financial_pg_engine):
    factory = create_session_factory(
        financial_pg_engine.url.render_as_string(hide_password=False)
    )
    transactions = SessionTransactionManager(factory)
    workflow = SqlAlchemyCustomerWorkflowRepository()
    with Session(financial_pg_engine) as session, session.begin():
        user = UserModel(
            user_id=uuid4(),
            username="followup-fixture",
            telegram_id="11111",
            messenger_type="telegram",
            status="active",
        )
        session.add(user)
        session.flush()
        user_id = user.user_id
        session.add(AdvertiserProfileModel(user_id=user_id, contact="fixture"))
        series_id, job_id = uuid4(), uuid4()
        session.execute(
            insert(SERIES).values(
                series_id=series_id,
                user_id=user_id,
                generation=1,
                created_at=AT - timedelta(hours=1),
                last_activity_at=AT,
                channel="telegram",
                opted_out=False,
            )
        )
        session.execute(
            insert(JOBS).values(
                job_id=job_id,
                series_id=series_id,
                recipient_id=user_id,
                stage=1,
                generation=1,
                due_at=AT,
                state="ready",
            )
        )
        session.add(
            AuditLogModel(
                entity_type=repo.CLIENT_REMINDER,
                entity_id=user_id,
                action=AuditAction.CREATE,
                changed_at=AT,
                new_values={"state": "sending"},
            )
        )
    async with transactions.transaction() as session:
        job = await workflow.claim(AT, 120, session=session)
        assert job is not None and job["job_id"] == job_id
        assert await workflow.eligible(job, AT, session=session) is None
        row = (
            (await session.execute(select(JOBS).where(JOBS.c.job_id == job_id)))
            .mappings()
            .one()
        )
        assert row["state"] == "ready" and row["due_at"] > AT
    await factory.kw["bind"].dispose()
