"""Real migrated checkout transactions and native one-charge authority."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_order_intake import command, service
from tests.postgres_financial.test_order_intake import intake_env as _intake_env
from ugc_bot.application.services.checkout_service import CheckoutService
from ugc_bot.domain.checkout import CheckoutActor
from ugc_bot.infrastructure.db.repositories.checkout import (
    SqlCheckoutRepository,
)


@pytest_asyncio.fixture
async def checkout_env(financial_pg_engine):
    async for env in _intake_env.__wrapped__(financial_pg_engine):
        order = await service(env).create(
            command(
                env,
                service_mode="with_manager",
                accompaniment_ordinals=frozenset({1, 7}),
            )
        )
        config = env["config"].model_copy(
            update={
                "bot": env["config"].bot.model_copy(
                    update={
                        "telegram_provider_token": "synthetic-provider",
                        "telegram_payment_account_id": "synthetic-account-"
                        + uuid4().hex,
                    }
                )
            }
        )
        repo = SqlCheckoutRepository(
            config,
            env["container"]
            .build_bot_services()["payment_service"]
            .capture_repository,
        )
        from ugc_bot.application.services.financial_policy_service import (
            FinancialPolicyService,
        )
        from ugc_bot.infrastructure.db.repositories.financial_capture import (
            SqlAlchemyFinancialCaptureRepository,
        )

        repo.capture = SqlAlchemyFinancialCaptureRepository(
            FinancialPolicyService(config.financial)
        )
        gateway = SimpleNamespace(
            create_link=AsyncMock(
                return_value="https://t.me/$synthetic_actual_link"
            )
        )
        from sqlalchemy.ext.asyncio import (
            async_sessionmaker,
            create_async_engine,
        )

        from ugc_bot.infrastructure.db.session import SessionTransactionManager

        engine = create_async_engine(financial_pg_engine.url, pool_size=4)
        transactions = SessionTransactionManager(
            async_sessionmaker(engine, expire_on_commit=False)
        )
        checkout = CheckoutService(repo, transactions, gateway, True, True)
        try:
            yield dict(
                env,
                transactions=transactions,
                order=order,
                config=config,
                checkout=checkout,
                checkout_repo=repo,
                gateway=gateway,
                actor=CheckoutActor(
                    env["user"].user_id, "telegram", env["user"].telegram_id
                ),
            )
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_frozen_quote_link_replay_and_no_transaction_during_io(
    checkout_env,
):
    env = checkout_env

    async def link(invoice):
        assert invoice.total_minor == 1740000
        with Session(env["pg"]) as db:
            assert (
                db.execute(
                    select(env["checkout_repo"].tables["requests"])
                ).first()
                is not None
            )
        return "https://t.me/$synthetic_actual_link"

    env["gateway"].create_link.side_effect = link
    first = await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "same"
    )
    assert first["invoice_state"] == "ready"
    assert first["amount_minor"] == 1740000
    second = await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "same"
    )
    assert second["invoice_url"] == first["invoice_url"]
    assert env["gateway"].create_link.await_count == 1
    assert first["capture_state"] == "not_recorded"


@pytest.mark.asyncio
async def test_two_precheckout_queries_authorize_at_most_one_before_paid(
    checkout_env,
):
    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )

    ready = asyncio.Event()
    connection_ids = set()

    async def authorize(query):
        from sqlalchemy import text

        async with env["transactions"].transaction() as session:
            connection_ids.add(
                await session.scalar(text("SELECT pg_backend_pid()"))
            )
            if len(connection_ids) == 2:
                ready.set()
            await ready.wait()
            return await env["checkout_repo"].authorize(
                env["order"].order_id,
                env["actor"].external_id,
                query,
                1740000,
                "RUB",
                session=session,
            )

    results = await asyncio.gather(
        authorize("query-one"), authorize("query-two"), return_exceptions=True
    )
    assert len(connection_ids) == 2
    assert sum(isinstance(result, dict) for result in results) == 1
    winner = next(result for result in results if isinstance(result, dict))
    assert await authorize(winner["query_id"]) == winner
    assert any(isinstance(result, ValueError) for result in results)


@pytest.mark.asyncio
async def test_unknown_link_retry_keeps_intent_and_payment_authorization(
    checkout_env,
):
    env = checkout_env
    env["gateway"].create_link.side_effect = TimeoutError("uncertain")
    unknown = await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    assert unknown["invoice_state"] == "unknown"
    env["gateway"].create_link.side_effect = None
    ready = await env["checkout"].retry_link(
        env["order"].order_id,
        env["actor"],
        "explicit-retry",
        unknown["attempt_id"],
    )
    assert ready["invoice_state"] == "ready"
    async with env["transactions"].transaction() as session:
        await env["checkout_repo"].authorize(
            env["order"].order_id,
            env["actor"].external_id,
            "approved",
            1740000,
            "RUB",
            session=session,
        )
    with pytest.raises(ValueError, match="payment_authorization_pending"):
        async with env[
            "container"
        ].transaction_manager.transaction() as session:
            await env["checkout_repo"].authorize(
                env["order"].order_id,
                env["actor"].external_id,
                "another",
                1740000,
                "RUB",
                session=session,
            )


@pytest.mark.asyncio
async def test_invoice_owner_and_signed_platform_are_current(checkout_env):
    env = checkout_env
    with pytest.raises(PermissionError):
        await env["checkout"].request_invoice(
            env["order"].order_id,
            replace(env["actor"], user_id=env["admin"].user_id),
            "foreign",
        )
    assert env["gateway"].create_link.await_count == 0


@pytest.mark.asyncio
async def test_admin_review_is_versioned_manual_and_cannot_release_receipt(
    checkout_env,
):
    from datetime import datetime, timezone

    from ugc_bot.domain.checkout import NativePaidReceipt

    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    async with env["transactions"].transaction() as session:
        authorization = await env["checkout_repo"].authorize(
            env["order"].order_id,
            env["actor"].external_id,
            "query",
            1740000,
            "RUB",
            session=session,
        )
    snapshot = await env["checkout"].status(env["order"].order_id, env["actor"])
    receipt = NativePaidReceipt(
        env["actor"].external_id,
        "actual-chat",
        "actual-message",
        env["order"].order_id,
        "provider-charge",
        "telegram-charge",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    async with env["transactions"].transaction() as session:
        assert await env["checkout_repo"].accept_receipt(
            receipt, session=session
        )
    admin = CheckoutActor(
        env["admin"].user_id, "telegram", env["admin"].telegram_id
    )
    with pytest.raises(ValueError, match="paid_receipt_pending"):
        async with env[
            "container"
        ].transaction_manager.transaction() as session:
            await env["checkout_repo"].review_authorization(
                authorization["authorization_id"],
                admin,
                "review-key",
                snapshot["version"],
                "Actual manual provider reconciliation review",
                "provider-case:actual-manual-evidence",
                session=session,
            )


@pytest.mark.asyncio
async def test_admin_review_releases_only_expected_authorization_and_immutable(
    checkout_env,
):
    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    async with env["transactions"].transaction() as session:
        auth = await env["checkout_repo"].authorize(
            env["order"].order_id,
            env["actor"].external_id,
            "first",
            1740000,
            "RUB",
            session=session,
        )
    snapshot = await env["checkout"].status(env["order"].order_id, env["actor"])
    admin = CheckoutActor(
        env["admin"].user_id, "telegram", env["admin"].telegram_id
    )

    async def review(reason="Actual manual provider reconciliation review"):
        async with env[
            "container"
        ].transaction_manager.transaction() as session:
            return await env["checkout_repo"].review_authorization(
                auth["authorization_id"],
                admin,
                "review",
                snapshot["version"],
                reason,
                "provider-case:actual-reviewed-evidence",
                session=session,
            )

    proof = await review()
    assert proof["source"] == "manual_admin_review"
    assert await review() == proof
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await review("Changed manual reconciliation justification")
    async with env["transactions"].transaction() as session:
        next_query = await env["checkout_repo"].authorize(
            env["order"].order_id,
            env["actor"].external_id,
            "second",
            1740000,
            "RUB",
            session=session,
        )
    assert next_query["authorization_id"] != auth["authorization_id"]


@pytest.mark.asyncio
async def test_native_paid_inbox_captures_after_restart_and_sales_pause(
    checkout_env,
):
    from datetime import datetime, timezone

    from ugc_bot.application.services.checkout_paid_receipts import (
        PaidReceiptProcessor,
    )
    from ugc_bot.domain.checkout import NativePaidReceipt

    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    paid = NativePaidReceipt(
        env["actor"].external_id,
        "trusted-chat",
        "native-message",
        env["order"].order_id,
        "provider-paid",
        "telegram-paid",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    async with env["transactions"].transaction() as session:
        assert await env["checkout_repo"].accept_receipt(paid, session=session)
    payment = replace(
        env["container"].build_bot_services()["payment_service"],
        capture_repository=env["checkout_repo"].capture,
        capture_account=env["config"].bot.telegram_payment_account_id,
    )
    processor = PaidReceiptProcessor(
        env["checkout_repo"], env["transactions"], payment
    )
    assert await processor.run_once()
    assert not await processor.run_once()
    snapshot = await env["checkout"].status(env["order"].order_id, env["actor"])
    assert snapshot["capture_state"] == "confirmed"
    assert snapshot["captured_at"] == paid.protocol_message_at
    assert not snapshot["can_open"]
    async with env["transactions"].transaction() as session:
        assert await env["checkout_repo"].accept_receipt(paid, session=session)
    assert not await processor.run_once()


@pytest.mark.asyncio
async def test_capture_commit_and_receipt_finish_are_replay_safe(checkout_env):
    from datetime import datetime, timezone

    from sqlalchemy import update

    from ugc_bot.application.services.checkout_paid_receipts import (
        PaidReceiptProcessor,
    )
    from ugc_bot.domain.checkout import NativePaidReceipt
    from ugc_bot.infrastructure.db.checkout_models import INBOX_STATE

    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    paid = NativePaidReceipt(
        env["actor"].external_id,
        "chat",
        "message",
        env["order"].order_id,
        "provider-charge",
        "tg-charge",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    async with env["transactions"].transaction() as session:
        await env["checkout_repo"].accept_receipt(paid, session=session)
    payment = replace(
        env["container"].build_bot_services()["payment_service"],
        capture_repository=env["checkout_repo"].capture,
        capture_account=env["config"].bot.telegram_payment_account_id,
    )
    processor = PaidReceiptProcessor(
        env["checkout_repo"], env["transactions"], payment
    )
    original = env["checkout_repo"].finish_receipt
    env["checkout_repo"].finish_receipt = AsyncMock(
        side_effect=RuntimeError("synthetic result commit failure")
    )
    with pytest.raises(RuntimeError):
        await processor.run_once()
    env["checkout_repo"].finish_receipt = original
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(INBOX_STATE)
            .where(INBOX_STATE.c.state == "processing")
            .values(lease_until=datetime(2000, 1, 1, tzinfo=timezone.utc))
        )
    assert await processor.run_once()
    assert (await env["checkout"].status(env["order"].order_id, env["actor"]))[
        "capture_state"
    ] == "confirmed"


@pytest.mark.asyncio
async def test_paid_worker_never_claims_another_provider_account(checkout_env):
    from datetime import datetime, timezone

    from ugc_bot.domain.checkout import NativePaidReceipt

    env = checkout_env
    receipt = NativePaidReceipt(
        env["actor"].external_id,
        "other-chat",
        "other-message",
        env["order"].order_id,
        "provider",
        "telegram",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    async with env["transactions"].transaction() as session:
        await env["checkout_repo"].accept_receipt(receipt, session=session)
    config = env["config"].model_copy(
        update={
            "bot": env["config"].bot.model_copy(
                update={"telegram_payment_account_id": "different-account"}
            )
        }
    )
    foreign = SqlCheckoutRepository(config, env["checkout_repo"].capture)
    async with env["transactions"].transaction() as session:
        assert await foreign.claim_receipt(session=session) is None


@pytest.mark.asyncio
async def test_paid_proof_survives_unknown_order_without_inventing_owner(
    checkout_env,
):
    from datetime import datetime, timezone

    from ugc_bot.domain.checkout import NativePaidReceipt

    env = checkout_env
    receipt = NativePaidReceipt(
        env["actor"].external_id,
        "retained-chat",
        "retained-message",
        uuid4(),
        "provider-unknown-order",
        "tg-unknown-order",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    async with env["transactions"].transaction() as session:
        assert await env["checkout_repo"].accept_receipt(
            receipt, session=session
        )
    with Session(env["pg"]) as db:
        assert (
            db.execute(
                select(env["checkout_repo"].tables["inbox"]).where(
                    env["checkout_repo"].tables["inbox"].c.order_id
                    == receipt.order_id
                )
            ).first()
            is not None
        )


@pytest.mark.asyncio
async def test_paid_notifications_are_durable_after_capture_and_unknown_resends(
    checkout_env,
):
    from datetime import datetime, timezone

    from ugc_bot.application.notice_delivery_ports import (
        DeliveryFailure,
        DeliveryReceipt,
    )
    from ugc_bot.application.services.checkout_paid_notices import (
        PaidNoticeDelivery,
    )
    from ugc_bot.application.services.checkout_paid_receipts import (
        PaidReceiptProcessor,
    )
    from ugc_bot.domain.checkout import NativePaidReceipt
    from ugc_bot.infrastructure.db.checkout_models import NOTICE_JOBS

    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    paid = NativePaidReceipt(
        env["actor"].external_id,
        "notice-chat",
        "notice-message",
        env["order"].order_id,
        "provider-notice",
        "tg-notice",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    async with env["transactions"].transaction() as session:
        await env["checkout_repo"].accept_receipt(paid, session=session)
    payment = replace(
        env["container"].build_bot_services()["payment_service"],
        capture_repository=env["checkout_repo"].capture,
        capture_account=env["config"].bot.telegram_payment_account_id,
    )
    assert await PaidReceiptProcessor(
        env["checkout_repo"], env["transactions"], payment
    ).run_once()
    transport = SimpleNamespace(send=AsyncMock())

    async def send(message):
        with Session(env["pg"]) as db:
            jobs = (
                db.execute(
                    select(NOTICE_JOBS).where(
                        NOTICE_JOBS.c.order_id == env["order"].order_id
                    )
                )
                .mappings()
                .all()
            )
            assert any(job.state == "sending" for job in jobs)
        assert (
            await env["checkout"].status(env["order"].order_id, env["actor"])
        )["capture_state"] == "confirmed"
        if message.address == env["actor"].external_id:
            raise DeliveryFailure("uncertain-after-acceptance", uncertain=True)
        return DeliveryReceipt("telegram", "synthetic-native-message")

    transport.send.side_effect = send
    delivery = PaidNoticeDelivery(
        env["checkout_repo"], env["transactions"], transport
    )
    with Session(env["pg"]) as db:
        from sqlalchemy import func

        queued = db.scalar(
            select(func.count())
            .select_from(NOTICE_JOBS)
            .where(NOTICE_JOBS.c.order_id == env["order"].order_id)
        )
    for _ in range(queued + 1):
        if not await delivery.run_once():
            break
    else:
        pytest.fail("notification queue did not drain")
    count = transport.send.await_count
    assert count >= 2
    assert not await delivery.run_once()
    assert transport.send.await_count == count
    assert (
        sum(
            call.args[0].address == env["actor"].external_id
            for call in transport.send.await_args_list
        )
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("paid_day,captured", [(1, True), (4, False)])
async def test_delayed_paid_processing_uses_native_occurrence_not_worker_time(
    checkout_env, monkeypatch, paid_day, captured
):
    from datetime import timedelta

    from sqlalchemy import update

    from ugc_bot.application.services.checkout_paid_receipts import (
        PaidReceiptProcessor,
    )
    from ugc_bot.domain.checkout import NativePaidReceipt
    from ugc_bot.infrastructure.db.checkout_models import INBOX, INBOX_STATE
    from ugc_bot.infrastructure.db.models import PaymentModel, UserModel
    from ugc_bot.infrastructure.db.repositories import checkout as adapter

    env = checkout_env
    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    paid = NativePaidReceipt(
        env["actor"].external_id,
        "delayed-chat",
        "delayed-message",
        env["order"].order_id,
        "delayed-provider",
        "delayed-telegram",
        1740000,
        "RUB",
        env["clock"].at + timedelta(days=paid_day),
    )
    monkeypatch.setattr(
        adapter, "now", lambda: env["clock"].at + timedelta(days=5)
    )
    # Rebuilt real Container also proves old invoices finish after sales pause
    # and account blocking. Only authenticated native receipt time is monetary.
    config = env["config"].model_copy(
        update={
            "financial": env["config"].financial.model_copy(
                update={"core_enabled": False, "new_orders_enabled": False}
            )
        }
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["actor"].user_id)
            .values(status="blocked")
        )
    from ugc_bot.container import Container

    container = Container(config)
    try:
        processor = PaidReceiptProcessor(
            env["checkout_repo"],
            env["transactions"],
            container.build_bot_services()["payment_service"],
        )
        assert await processor.accept(paid)
        assert await processor.run_once()
        with Session(env["pg"]) as db:
            payment = db.scalar(
                select(PaymentModel).where(
                    PaymentModel.order_id == paid.order_id
                )
            )
            state = (
                db.execute(
                    select(INBOX_STATE)
                    .join(INBOX)
                    .where(INBOX.c.order_id == paid.order_id)
                )
                .mappings()
                .one()
            )
            assert state.state == ("captured" if captured else "unresolved")
            assert payment.paid_at == (
                paid.protocol_message_at if captured else None
            )
            assert payment.captured_minor == (1740000 if captured else None)
        assert not await processor.run_once()
    finally:
        await container.session_factory.kw["bind"].dispose()
