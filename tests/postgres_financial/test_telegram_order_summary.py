"""Telegram summary decisions on actual paid positions and reserve interests."""

import asyncio
import os
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_order_intake import (
    Clock,
    command,
    intake_env,
    service,
)
from tests.postgres_financial.test_replacements import capture_env
from tests.postgres_financial.test_replacements import (
    setup as captured_replacements,
)
from ugc_bot.application.collaboration_ports import CollaborationCommand
from ugc_bot.application.financial_ports import IssueBasis
from ugc_bot.application.messenger.dto import PaymentSuccess
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyService,
)
from ugc_bot.application.services.order_support_service import (
    OrderSupportService,
)
from ugc_bot.bot.telegram.handlers.order_summary import render_card
from ugc_bot.bot.telegram.order_summary_runtime import run_once
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.container.order_summary_factory import build_order_summary
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.customer_workflow_models import REQUESTS
from ugc_bot.infrastructure.db.models import (
    FinancialMovementModel,
    OrderModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.order_summary_models import JOBS, REPORTS
from ugc_bot.infrastructure.db.replacement_models import TABLES
from ugc_bot.infrastructure.db.repositories.financial_capture import (
    SqlAlchemyFinancialCaptureRepository,
)

__all__ = ["capture_env", "intake_env"]


@pytest.fixture
def financial_pg_engine(request):
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        if request.config.getoption("--require-financial-postgres"):
            pytest.fail("FINANCIAL_TEST_DATABASE_URL is required")
        pytest.skip("Local unit-only run: FINANCIAL_TEST_DATABASE_URL not set")
    with isolated_financial_database(url) as engine:
        yield engine


def fake_telegram():
    ids = iter(range(1, 300))
    return SimpleNamespace(
        send_message=AsyncMock(
            side_effect=lambda **kwargs: SimpleNamespace(
                message_id=next(ids), chat=SimpleNamespace(id=kwargs["chat_id"])
            ),
        )
    )


async def paid_order(env, *, size=10, interested_creators=None):
    oid = (
        await service(env).create(command(env, position_count=size))
    ).order_id
    container = env["container"]
    deps = container.build_bot_services()
    payments = deps["payment_service"]
    payments.capture_account = "summary-synthetic"
    payments.capture_repository = SqlAlchemyFinancialCaptureRepository(
        FinancialPolicyService(env["config"].financial)
    )
    user = env["user"]
    tm = container.transaction_manager
    async with tm.transaction() as session:
        amount, currency = await payments.capture_repository.issue(
            oid, user.user_id, payments.capture_account, session=session
        )
    total = int(amount * 100)
    receipt = PaymentSuccess(
        str(oid),
        str(uuid4()),
        total,
        currency,
        env["clock"].at,
        str(uuid4()),
    )
    await payments.confirm_telegram_payment(
        user.user_id,
        oid,
        receipt.provider_payment_charge_id,
        total,
        currency,
        receipt=receipt,
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == oid)
            .values(status=OrderStatus.ACTIVE)
        )
    from tests.postgres_financial.test_creator_social import seed_profile

    creators = []
    with env["pg"].begin() as db:
        for _ in range(
            interested_creators if interested_creators is not None else size + 3
        ):
            cid = seed_profile(db, stable_id=uuid4().hex)
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == cid)
                .values(
                    telegram_id=str(cid.int % 10**12 + 1),
                    status="active",
                )
            )
            creators.append(cid)
    interests = [
        await deps["offer_response_service"].paid_selection_service.respond(
            oid, cid
        )
        for cid in creators
    ]
    bot = fake_telegram()
    delivery = container.build_paid_selection_delivery(bot)
    await delivery.run_once()
    config = env["config"].model_copy(
        update={
            "order": env["config"].order.model_copy(
                update={"customer_workflows_enabled": True}
            ),
        }
    )
    summary = build_order_summary(config, tm)
    summary.clock = env["clock"]
    summary.collaboration.clock = env["clock"]
    summary.replacement.clock = env["clock"]
    summary.maturity.clock = env["clock"]
    env["clock"].at = receipt.protocol_message_at + timedelta(minutes=1)
    principal = AuthenticatedMessengerPrincipal(
        user.user_id, "telegram", user.telegram_id
    )
    bot.send_message.reset_mock()
    return summary, oid, interests, principal, bot


async def seed_pending_referrals(summary, env, oid, interests):
    with Session(env["pg"]) as db:
        payment = db.scalar(
            select(PaymentModel).where(PaymentModel.order_id == oid)
        )
    async with summary.transactions.transaction() as session:
        ledger = summary.replacement.ledger
        return [
            (
                await ledger.issue(
                    IssueBasis(
                        business_key=f"synthetic-old:{interest.assignment_id}",
                        kind="creator_referral",
                        recipient_id=env["user"].user_id,
                        paid_item_id=interest.paid_item_id,
                        order_id=oid,
                        assignment_id=interest.assignment_id,
                        referred_user_id=interest.creator_id,
                        payment_id=payment.payment_id,
                        currency="RUB",
                        base_minor=50000,
                        rate_bps=1000,
                        policy_version=env["policy"],
                        snapshot_at=payment.paid_at,
                        registered_at=payment.paid_at - timedelta(days=1),
                        verified_count=0,
                        event_id="synthetic-old-ground",
                        reason="Original creator obligation",
                        actor_id=env["admin"].user_id,
                    ),
                    recorded_at=payment.paid_at,
                    session=session,
                )
            ).obligation_id
            for interest in interests
        ]


@pytest.mark.asyncio
async def test_bulk_report_24h_reserve_limit_and_single_reminder(intake_env):
    env = intake_env
    summary, oid, interests, principal, bot = await paid_order(env)
    with pytest.raises(ValueError, match="financial_principal_changed"):
        await summary.view(replace(principal, external_id="wrong"), oid)
    data = await summary.view(principal, oid, action="exceptions")
    assert len(data["positions"]) == 10 and data["limit"] == 2
    old_grounds = await seed_pending_referrals(summary, env, oid, interests[:3])
    draft = data["draft_id"]
    for interest in interests[:3]:
        data = await summary.view(
            principal,
            None,
            action="pick",
            draft_id=draft,
            assignment_id=interest.assignment_id,
            reason="no_answer",
        )
    text, keyboard = render_card(summary, data, "exceptions")
    assert "Выбрано: 3" in text
    assert all(
        len(b.callback_data.encode()) <= 64
        for row in keyboard.rows
        for b in row
    )
    await summary.view(principal, None, action="save", draft_id=draft)
    await summary.view(principal, oid, action="remind1")
    await summary.view(principal, oid, action="remind3")
    await run_once(summary, bot)
    assert bot.send_message.await_count == 3
    env["clock"].at += timedelta(hours=24) - timedelta(seconds=1)
    await run_once(summary, bot)
    with Session(env["pg"]) as db:
        assert (
            db.scalar(select(func.count()).select_from(TABLES["allocations"]))
            == 0
        )
    env["clock"].at += timedelta(seconds=1)
    await asyncio.gather(run_once(summary, bot), run_once(summary, bot))
    await run_once(summary, bot)
    with Session(env["pg"]) as db:
        report_states = list(
            db.scalars(select(REPORTS.c.state).where(REPORTS.c.order_id == oid))
        )
        assert sorted(report_states) == ["replaced", "replaced", "review"]
        reversals = list(
            db.scalars(
                select(FinancialMovementModel).where(
                    FinancialMovementModel.obligation_id.in_(old_grounds),
                    FinancialMovementModel.movement_type == "reversal",
                )
            )
        )
        assert len(reversals) == 2
        assert all(
            row.actor_kind == "system"
            and row.system_actor == "telegram_order_summary"
            and row.bucket_to == "cancelled"
            for row in reversals
        )
        assert (
            db.scalar(select(func.count()).select_from(TABLES["allocations"]))
            == 2
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(JOBS)
                .where(
                    JOBS.c.order_id == oid,
                    JOBS.c.kind == "reminder",
                    JOBS.c.state == "sent",
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(REQUESTS)
                .where(REQUESTS.c.order_id == oid)
            )
            == 1
        )
    assert bot.send_message.await_count == 4
    data = await summary.view(principal, oid)
    replacement = next(
        row for row in data["positions"] if row["replacement_id"]
    )
    contact_order, contact = await summary.contact(
        principal, replacement["replacement_id"]
    )
    assert contact_order == oid and "instagram.com" in contact


@pytest.mark.asyncio
async def test_unknown_delivery_and_creator_answer_prevent_auto_replacement(
    intake_env,
):
    env = intake_env
    summary, oid, interests, principal, bot = await paid_order(env)
    draft = (await summary.view(principal, oid, action="exceptions"))[
        "draft_id"
    ]
    for interest in interests[:2]:
        await summary.view(
            principal,
            None,
            action="pick",
            draft_id=draft,
            assignment_id=interest.assignment_id,
            reason="no_answer",
        )
    await summary.view(principal, None, action="save", draft_id=draft)

    attempts = iter((False, True))

    async def uncertain_once(**kwargs):
        if not next(attempts):
            raise TimeoutError
        return SimpleNamespace(
            message_id=2, chat=SimpleNamespace(id=kwargs["chat_id"])
        )

    bot.send_message.side_effect = uncertain_once
    await run_once(summary, bot)
    with Session(env["pg"]) as db:
        report = (
            db.execute(
                select(REPORTS).where(
                    REPORTS.c.order_id == oid, REPORTS.c.state == "waiting"
                )
            )
            .mappings()
            .one()
        )
        creator = db.get(UserModel, report["creator_id"])
        author = AuthenticatedMessengerPrincipal(
            creator.user_id, "telegram", creator.telegram_id
        )
    assert await summary.creator_answer(author, report["report_id"])
    env["clock"].at += timedelta(hours=24)
    await run_once(summary, bot)
    with Session(env["pg"]) as db:
        assert sorted(
            db.scalars(select(REPORTS.c.state).where(REPORTS.c.order_id == oid))
        ) == ["answered", "review"]
        assert (
            db.scalar(
                select(func.count())
                .select_from(TABLES["allocations"])
                .join(TABLES["decisions"])
                .where(TABLES["decisions"].c.order_id == oid)
            )
            == 0
        )


@pytest.mark.asyncio
async def test_summary_confirms_claim_and_retains_financial_lifecycle(
    intake_env,
):
    env = intake_env
    summary, oid, interests, principal, _ = await paid_order(env)
    assignment = interests[0].assignment_id
    with Session(env["pg"]) as db:
        user = db.get(UserModel, interests[0].creator_id)
        creator = AuthenticatedMessengerPrincipal(
            user.user_id, "telegram", user.telegram_id
        )

    async def act(actor, action, version, **kwargs):
        async with summary.transactions.transaction() as session:
            return await summary.collaboration.execute_authenticated(
                CollaborationCommand(
                    assignment_id=assignment,
                    action=action,
                    operation_key=f"test:{action}",
                    expected_version=version,
                    actor_id=actor.user_id,
                    **kwargs,
                ),
                actor,
                session=session,
            )

    await act(
        principal,
        "assign",
        0,
        due_at=env["clock"].at + timedelta(days=1),
        terms_reference="synthetic terms",
    )
    await act(principal, "start", 1)
    await act(creator, "claim", 2, evidence="https://example.test/completed")
    data = await summary.view(principal, oid)
    key = summary.confirmation_key(data["positions"], principal.user_id)
    with pytest.raises(ValueError, match="summary_confirmation_changed"):
        await summary.view(
            principal, oid, action="confirm", confirmation="stale"
        )
    data = await summary.view(
        principal, oid, action="confirm", confirmation=key
    )
    assert data["positions"][0]["work_state"] == "success_final"
    assert all(row["work_state"] is None for row in data["positions"][1:])
    async with summary.transactions.transaction() as session:
        result = await summary.collaboration.repository.get(
            assignment, session=session
        )
    assert result.collaboration.available_at == env["clock"].at + timedelta(
        days=14
    )


@pytest.mark.asyncio
async def test_paid_selection_closes_after_silence_with_one_order_reminder(
    intake_env,
):
    env = intake_env
    summary, oid, _, principal, bot = await paid_order(env)
    env["clock"].at += timedelta(days=3)
    await run_once(summary, bot)
    await run_once(summary, bot)
    assert bot.send_message.await_count == 1
    assert "Итоги заказа" in bot.send_message.await_args.kwargs["text"]

    env["clock"].at += timedelta(days=3)
    await run_once(summary, bot)
    await run_once(summary, bot)
    assert bot.send_message.await_count == 2
    assert "Напоминание" in bot.send_message.await_args.kwargs["text"]

    env["clock"].at += timedelta(days=2)
    await run_once(summary, bot)
    await run_once(summary, bot)
    assert bot.send_message.await_count == 2
    data = await summary.view(principal, oid)
    assert data["work_closed"]
    assert all(row["work_state"] is None for row in data["positions"])
    with Session(env["pg"]) as db:
        assert db.get(OrderModel, oid).status == OrderStatus.CLOSED
        assert db.get(OrderModel, oid).dispatch_stopped


@pytest.mark.asyncio
async def test_small_paid_package_routes_no_response_to_manual_review(
    capture_env,
):
    env = capture_env
    _, interests, _, principal, _ = await captured_replacements(env)
    oid = env["order"]
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": env["pg"].url.render_as_string(hide_password=False),
            "FINANCIAL_CORE_ENABLED": True,
            "CUSTOMER_WORKFLOWS_ENABLED": True,
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
        }
    )
    container = Container(config)

    try:
        bot = fake_telegram()
        await container.build_paid_selection_delivery(bot).run_once()
        summary = build_order_summary(config, container.transaction_manager)
        summary.clock = Clock()
        await check_small_package(summary, oid, interests, principal, bot, env)
    finally:
        await container.session_factory.kw["bind"].dispose()


async def check_small_package(summary, oid, interests, principal, bot, env):
    data = await summary.view(principal, oid, action="exceptions")
    assert data["limit"] == 0
    await summary.view(
        principal,
        None,
        action="pick",
        draft_id=data["draft_id"],
        assignment_id=interests[0].assignment_id,
        reason="no_answer",
    )
    await summary.view(
        principal, None, action="save", draft_id=data["draft_id"]
    )
    await run_once(summary, bot)
    summary.clock.at += timedelta(hours=24)
    await run_once(summary, bot)
    with Session(env["pg"]) as db:
        report = (
            db.execute(select(REPORTS).where(REPORTS.c.order_id == oid))
            .mappings()
            .one()
        )
        assert report["state"] == "review"
        assert report["review_reason"] == "replacement_reserve_limit_reached"
        request_id = report["support_request_id"]
        admin = db.scalar(select(UserModel).where(UserModel.admin.is_(True)))
        admin_principal = AuthenticatedMessengerPrincipal(
            admin.user_id, "telegram", admin.telegram_id
        )
    support = OrderSupportService(
        summary.repository, summary.transactions, summary.clock
    )
    await support.update_status(
        admin_principal.user_id,
        request_id,
        "resolved",
        principal=admin_principal,
    )
    data = await summary.view(principal, oid)
    assert data["positions"][0]["report_state"] == "reviewed"
    assert data["positions"][0]["work_state"] is None


@pytest.mark.asyncio
async def test_withdrawn_draft_and_unfilled_paid_positions(intake_env):
    env = intake_env
    summary, oid, interests, principal, bot = await paid_order(
        env, interested_creators=2
    )
    data = await summary.view(principal, oid, action="exceptions")
    draft = data["draft_id"]
    assignment = interests[0].assignment_id
    for _ in range(2):
        await summary.view(
            principal,
            None,
            action="pick",
            draft_id=draft,
            assignment_id=assignment,
            reason="no_answer",
        )
    await summary.view(principal, None, action="discard", draft_id=draft)
    with pytest.raises(PermissionError, match="summary_order_unavailable"):
        await summary.view(principal, None, action="save", draft_id=draft)

    data = await summary.view(principal, oid, action="exceptions")
    draft = data["draft_id"]
    await summary.view(
        principal,
        None,
        action="pick",
        draft_id=draft,
        assignment_id=assignment,
        reason="no_answer",
    )
    data = await summary.view(principal, None, action="save", draft_id=draft)
    await summary.view(
        principal,
        None,
        action="withdraw",
        report_id=data["positions"][0]["report_id"],
    )
    await run_once(summary, bot)
    bot.send_message.assert_not_awaited()

    env["clock"].at += timedelta(days=4)
    await run_once(summary, bot)
    await run_once(summary, bot)
    with Session(env["pg"]) as db:
        assert db.get(OrderModel, oid).status == OrderStatus.ACTIVE
        reviews = (
            db.execute(
                select(REQUESTS.c.payload).where(REQUESTS.c.order_id == oid)
            )
            .scalars()
            .all()
        )
    assert len(reviews) == 1
    assert len(reviews[0]["reports"]) == 8
    assert {r["reason"] for r in reviews[0]["reports"]} == {
        "contact_or_refund_unconfirmed"
    }
