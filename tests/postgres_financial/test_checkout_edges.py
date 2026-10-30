"""Trusted checkout transactions and native provider boundaries."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.postgres_financial.test_checkout_runtime import (
    checkout_env as _checkout_env,
)
from ugc_bot.domain.checkout import CheckoutActor, NativePaidReceipt
from ugc_bot.infrastructure.db.checkout_models import (
    NOTICE_JOBS,
    NOTICE_RESULTS,
)
from ugc_bot.infrastructure.db.models import (
    OrderModel,
    OutboxEventModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import intent_id


@pytest_asyncio.fixture
async def checkout_env(financial_pg_engine):
    async for env in _checkout_env.__wrapped__(financial_pg_engine):
        yield env


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "missing_order",
        "foreign_owner",
        "legacy",
        "long_key",
        "retry_before_issue",
        "not_new",
    ],
)
async def test_invoice_rejects_wrong_order_or_command_before_remote_io(
    checkout_env, case
):
    env = checkout_env
    order = env["order"].order_id
    actor = env["actor"]
    key = "issue"
    if case == "missing_order":
        order = uuid4()
    elif case == "foreign_owner":
        actor = CheckoutActor(
            env["admin"].user_id, "telegram", env["admin"].telegram_id
        )
    elif case == "long_key":
        key = "x" * 257
    elif case in {"legacy", "not_new"}:
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(OrderModel)
                .where(OrderModel.order_id == order)
                .values(
                    **(
                        {"financial_version": None}
                        if case == "legacy"
                        else {"status": "pending_moderation"}
                    )
                )
            )
    with pytest.raises((ValueError, LookupError, PermissionError)):
        if case == "retry_before_issue":
            await env["checkout"].retry_link(order, actor, key, uuid4())
        else:
            await env["checkout"].request_invoice(order, actor, key)
    env["gateway"].create_link.assert_not_awaited()


@pytest.mark.asyncio
async def test_ready_reuses_link_for_new_click_and_conflicts_when_changes(
    checkout_env,
):
    env = checkout_env
    order = env["order"].order_id
    first = await env["checkout"].request_invoice(order, env["actor"], "issue")
    assert (
        await env["checkout"].request_invoice(order, env["actor"], "second")
        == first
    )
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await env["checkout"].retry_link(order, env["actor"], "issue", uuid4())
    assert env["gateway"].create_link.await_count == 1


@pytest.mark.asyncio
async def test_unknown_link_requires_explicit_matching_attempt_and_blocks_retry(
    checkout_env,
):
    env = checkout_env
    order = env["order"].order_id
    env["gateway"].create_link.side_effect = TimeoutError()
    first = await env["checkout"].request_invoice(order, env["actor"], "issue")
    assert (
        await env["checkout"].request_invoice(order, env["actor"], "check-only")
        == first
    )
    with pytest.raises(ValueError, match="checkout_attempt_changed"):
        await env["checkout"].retry_link(order, env["actor"], "wrong", uuid4())
    await env["checkout"].authorize(
        order, env["actor"].external_id, "query", 1740000, "RUB"
    )
    with pytest.raises(ValueError, match="payment_authorization_pending"):
        await env["checkout"].retry_link(
            order, env["actor"], "explicit", first["attempt_id"]
        )
    assert env["gateway"].create_link.await_count == 1


@pytest.mark.asyncio
async def test_inflight_expired_link_is_unknown_and_late_result_cannot_retry(
    checkout_env, monkeypatch
):
    from ugc_bot.infrastructure.db.repositories import checkout as adapter

    env = checkout_env
    repo = env["checkout_repo"]
    order = env["order"].order_id
    async with env["transactions"].transaction() as db:
        prepared = await repo.prepare(
            order,
            env["actor"],
            "first",
            allow_new=True,
            retry_of=None,
            session=db,
        )
    creating = await env["checkout"].request_invoice(
        order, env["actor"], "while-creating"
    )
    assert creating["invoice_state"] == "creating"
    monkeypatch.setattr(
        adapter, "now", lambda: env["clock"].at + timedelta(minutes=3)
    )
    assert (await env["checkout"].status(order, env["actor"]))[
        "invoice_state"
    ] == "unknown"
    ready = await env["checkout"].retry_link(
        order, env["actor"], "new-link", prepared.attempt_id
    )
    async with env["transactions"].transaction() as db:
        stale = await repo.complete(
            prepared, outcome="ready", url="https://t.me/$old_late", session=db
        )
    assert (
        stale["attempt_id"] == ready["attempt_id"]
        and stale["invoice_url"] == ready["invoice_url"]
    )


@pytest.mark.asyncio
async def test_untracked_existing_intent_is_never_automatically_adopted(
    checkout_env,
):
    env = checkout_env
    order = env["order"].order_id
    async with env["transactions"].transaction() as db:
        await env["checkout_repo"].capture.issue(
            order,
            env["actor"].user_id,
            env["checkout_repo"].account,
            session=db,
        )
    assert (
        await env["checkout"].request_invoice(order, env["actor"], "issue")
    )["invoice_state"] == "untracked"
    env["gateway"].create_link.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("linked", [True, False])
async def test_max_status_needs_actual_canonical_link_not_equal_numeric_id(
    checkout_env, linked
):
    env = checkout_env
    order = env["order"].order_id
    env["config"].bot.bot_username = "actual_bot"
    max_id = "max-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["actor"].user_id)
            .values(
                max_id=max_id,
                telegram_id=env["actor"].external_id if linked else None,
            )
        )
    value = await env["checkout"].status(
        order, replace(env["actor"], platform="max", external_id=max_id)
    )
    assert value["invoice_url"] is None and not value["can_open"]
    assert bool(value["telegram_handoff"]) == linked


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["pending_moderation", "active", "closed", "deleted"]
)
@pytest.mark.parametrize("issued", [False, True])
async def test_terminal_order_status_does_not_offer_invoice_or_handoff(
    checkout_env, status, issued
):
    env = checkout_env
    order_id = env["order"].order_id
    env["config"].bot.bot_username = "actual_bot"
    max_id = "max-" + uuid4().hex
    if issued:
        await env["checkout"].request_invoice(order_id, env["actor"], "issue")
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["actor"].user_id)
            .values(max_id=max_id)
        )
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == order_id)
            .values(status=status)
        )

    telegram = await env["checkout"].status(order_id, env["actor"])
    assert telegram["order_open_for_payment"] is False
    assert telegram["can_open"] is False
    assert telegram["invoice_url"] is None
    if issued:
        replay = await env["checkout"].request_invoice(
            order_id, env["actor"], "issue"
        )
        assert replay["invoice_url"] is None and not replay["can_open"]
        assert env["gateway"].create_link.await_count == 1
    max_value = await env["checkout"].status(
        order_id, replace(env["actor"], platform="max", external_id=max_id)
    )
    assert max_value["order_open_for_payment"] is False
    assert max_value["telegram_handoff"] is None


@pytest.mark.asyncio
async def test_terminal_order_keeps_authorization_replayable(
    checkout_env,
):
    env = checkout_env
    order_id = env["order"].order_id
    await env["checkout"].request_invoice(order_id, env["actor"], "issue")
    authorization = await env["checkout"].authorize(
        order_id, env["actor"].external_id, "pending-query", 1740000, "RUB"
    )
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == order_id)
            .values(status="deleted")
        )
    state = await env["checkout"].status(order_id, env["actor"])
    assert state["order_open_for_payment"] is False
    assert state["authorization_id"] == authorization["authorization_id"]
    assert state["invoice_url"] is None and not state["can_open"]
    replay = await env["checkout"].authorize(
        order_id, env["actor"].external_id, "pending-query", 1740000, "RUB"
    )
    assert replay["authorization_id"] == authorization["authorization_id"]


@pytest.mark.asyncio
async def test_pending_receipt_prevents_new_authorization_even_before_capture(
    checkout_env,
):
    env = checkout_env
    order = env["order"].order_id
    await env["checkout"].request_invoice(order, env["actor"], "issue")
    receipt = NativePaidReceipt(
        env["actor"].external_id,
        "chat",
        "msg",
        order,
        "provider",
        "telegram",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    async with env["transactions"].transaction() as db:
        await env["checkout_repo"].accept_receipt(receipt, session=db)
    with pytest.raises(ValueError, match="paid_receipt_pending"):
        await env["checkout"].authorize(
            order, env["actor"].external_id, "new", 1740000, "RUB"
        )


@pytest.mark.asyncio
async def test_native_query_replay_after_manual_release_is_rejected(
    checkout_env,
):
    env = checkout_env
    order = env["order"].order_id
    await env["checkout"].request_invoice(order, env["actor"], "issue")
    auth = await env["checkout"].authorize(
        order, env["actor"].external_id, "query", 1740000, "RUB"
    )
    admin = CheckoutActor(
        env["admin"].user_id, "telegram", env["admin"].telegram_id
    )
    await env["checkout"].review_authorization(
        auth["authorization_id"],
        admin,
        "review",
        (await env["checkout"].status(order, env["actor"]))["version"],
        "Actual provider support disposition reviewed",
        "case:actual-reference",
    )
    with pytest.raises(ValueError, match="native_query_conflict"):
        await env["checkout"].authorize(
            order, env["actor"].external_id, "query", 1740000, "RUB"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing_order", "untracked", "not_payable"])
async def test_native_authorization_requires_known_current_payable_checkout(
    checkout_env, case
):
    env = checkout_env
    order = env["order"].order_id
    if case == "missing_order":
        order = uuid4()
    elif case == "not_payable":
        await env["checkout"].request_invoice(order, env["actor"], "issue")
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(PaymentModel)
                .where(PaymentModel.order_id == order)
                .values(status="failed")
            )
    with pytest.raises((ValueError, LookupError)):
        await env["checkout"].authorize(
            order, env["actor"].external_id, "query", 1740000, "RUB"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "short_reason",
        "missing_authorization",
        "owner_changed",
        "unknown_paid_projection",
    ],
)
async def test_manual_release_requires_reason_known_original_owner_and_source(
    checkout_env, case
):
    env = checkout_env
    order = env["order"].order_id
    await env["checkout"].request_invoice(order, env["actor"], "issue")
    auth = await env["checkout"].authorize(
        order, env["actor"].external_id, "query", 1740000, "RUB"
    )
    admin = CheckoutActor(
        env["admin"].user_id, "telegram", env["admin"].telegram_id
    )
    version = (await env["checkout"].status(order, env["actor"]))["version"]
    if case == "owner_changed":
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(OrderModel)
                .where(OrderModel.order_id == order)
                .values(advertiser_id=admin.user_id)
            )
    elif case == "unknown_paid_projection":
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(PaymentModel)
                .where(PaymentModel.order_id == order)
                .values(status="paid")
            )
    with pytest.raises((ValueError, LookupError)):
        await env["checkout"].review_authorization(
            uuid4()
            if case == "missing_authorization"
            else auth["authorization_id"],
            admin,
            "review",
            version,
            "short"
            if case == "short_reason"
            else "Actual provider support disposition reviewed",
            "case:actual-reference",
        )


@pytest.mark.asyncio
async def test_malformed_stored_capture_timestamp_is_unavailable_not_500(
    checkout_env,
):
    from ugc_bot.infrastructure.db.repositories.financial_capture import (
        capture_id,
    )

    env = checkout_env
    order = env["order"].order_id
    await env["checkout"].request_invoice(order, env["actor"], "issue")
    with Session(env["pg"]) as db, db.begin():
        intent = db.get(OutboxEventModel, intent_id(order))
        payment = db.scalar(
            select(PaymentModel).where(PaymentModel.order_id == order)
        )
        at = datetime.now(timezone.utc)
        payment.captured_minor = 1740000
        payment.paid_at = at
        payment.external_id = "invalid-proof"
        db.add(
            OutboxEventModel(
                event_id=capture_id(
                    env["checkout_repo"].account, "invalid-proof"
                ),
                event_type="financial.client_snapshot_requested",
                aggregate_type="order",
                aggregate_id=str(order),
                payload={
                    "payment_id": str(payment.payment_id),
                    "capture": dict(
                        intent.payload,
                        external_id="invalid-proof",
                        telegram_payment_charge_id="native",
                        captured_at="not-a-timestamp",
                    ),
                },
            )
        )
    assert (await env["checkout"].status(order, env["actor"]))[
        "capture_state"
    ] == "unavailable"


async def captured_notices(env):
    from ugc_bot.application.services.checkout_paid_receipts import (
        PaidReceiptProcessor,
    )

    await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    receipt = NativePaidReceipt(
        env["actor"].external_id,
        "notice-chat",
        "notice-msg",
        env["order"].order_id,
        "notice-provider",
        "notice-telegram",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    payments = replace(
        env["container"].build_bot_services()["payment_service"],
        capture_repository=env["checkout_repo"].capture,
        capture_account=env["checkout_repo"].account,
    )
    processor = PaidReceiptProcessor(
        env["checkout_repo"], env["transactions"], payments
    )
    await processor.accept(receipt)
    await processor.run_once()
    # Other historical active admins are valid production recipients. Restrict
    # this test to its client job, without changing global account/admin truth.
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(NOTICE_JOBS)
            .where(
                NOTICE_JOBS.c.order_id == env["order"].order_id,
                NOTICE_JOBS.c.kind == "admin",
            )
            .values(state="obsolete")
        )


@pytest.mark.asyncio
async def test_notice_expired_send_and_late_proof_never_resends_unknown(
    checkout_env, monkeypatch
):
    from ugc_bot.infrastructure.db.repositories import checkout as adapter

    env = checkout_env
    repo = env["checkout_repo"]
    await captured_notices(env)
    async with env["transactions"].transaction() as db:
        notice = await repo.claim_notice(session=db)
    monkeypatch.setattr(
        adapter, "now", lambda: env["clock"].at + timedelta(minutes=5)
    )
    async with env["transactions"].transaction() as db:
        assert await repo.claim_notice(session=db) is None
    async with env["transactions"].transaction() as db:
        await repo.finish_notice(notice, "accepted", "late-proof", session=db)
    async with env["transactions"].transaction() as db:
        await repo.finish_notice(notice, "accepted", "late-proof", session=db)
    with Session(env["pg"]) as db:
        assert (
            db.execute(
                select(NOTICE_JOBS.c.state).where(
                    NOTICE_JOBS.c.job_id == notice.job_id
                )
            ).scalar_one()
            == "unknown"
        )
        assert (
            db.execute(
                select(NOTICE_RESULTS.c.applied).where(
                    NOTICE_RESULTS.c.attempt_id == notice.attempt_id,
                    NOTICE_RESULTS.c.outcome == "accepted",
                )
            ).scalar_one()
            is False
        )


@pytest.mark.asyncio
async def test_definite_notice_failures_retry_three_times_then_stop(
    checkout_env, monkeypatch
):
    from ugc_bot.infrastructure.db.repositories import checkout as adapter

    env = checkout_env
    repo = env["checkout_repo"]
    await captured_notices(env)
    at = datetime.now(timezone.utc)
    for attempt in range(3):
        monkeypatch.setattr(
            adapter,
            "now",
            lambda attempt=attempt: at + timedelta(minutes=attempt),
        )
        async with env["transactions"].transaction() as db:
            notice = await repo.claim_notice(session=db)
        assert notice is not None
        async with env["transactions"].transaction() as db:
            await repo.finish_notice(notice, "failed", None, session=db)
    async with env["transactions"].transaction() as db:
        assert await repo.claim_notice(session=db) is None
    with Session(env["pg"]) as db:
        assert (
            db.execute(
                select(NOTICE_JOBS.c.state).where(
                    NOTICE_JOBS.c.job_id == notice.job_id
                )
            ).scalar_one()
            == "failed"
        )


@pytest.mark.asyncio
async def test_removed_native_contact_obsoletes_notice_without_send(
    checkout_env,
):
    env = checkout_env
    await captured_notices(env)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["actor"].user_id)
            .values(telegram_id=None)
        )
    async with env["transactions"].transaction() as db:
        assert await env["checkout_repo"].claim_notice(session=db) is None
    with Session(env["pg"]) as db:
        assert (
            db.execute(
                select(NOTICE_JOBS.c.state).where(
                    NOTICE_JOBS.c.order_id == env["order"].order_id,
                    NOTICE_JOBS.c.kind == "client",
                )
            ).scalar_one()
            == "obsolete"
        )


@pytest.mark.asyncio
async def test_expired_link_retry_fails_before_new_remote_creation(
    checkout_env, monkeypatch
):
    from ugc_bot.application.errors import OrderCreationError
    from ugc_bot.infrastructure.db.repositories import checkout as adapter

    env = checkout_env
    env["gateway"].create_link.side_effect = TimeoutError("uncertain creation")
    first = await env["checkout"].request_invoice(
        env["order"].order_id, env["actor"], "issue"
    )
    monkeypatch.setattr(
        adapter, "now", lambda: env["clock"].at + timedelta(days=4)
    )
    with pytest.raises(OrderCreationError):
        await env["checkout"].retry_link(
            env["order"].order_id,
            env["actor"],
            "expired-retry",
            first["attempt_id"],
        )
    assert env["gateway"].create_link.await_count == 1


@pytest.mark.asyncio
async def test_manual_release_waits_for_uncommitted_native_paid_receipt(
    checkout_env,
):
    import asyncio

    env = checkout_env
    order = env["order"].order_id
    await env["checkout"].request_invoice(order, env["actor"], "issue")
    auth = await env["checkout"].authorize(
        order, env["actor"].external_id, "query", 1740000, "RUB"
    )
    version = (await env["checkout"].status(order, env["actor"]))["version"]
    receipt = NativePaidReceipt(
        env["actor"].external_id,
        "race-chat",
        "race-message",
        order,
        "race-provider",
        "race-telegram",
        1740000,
        "RUB",
        datetime.now(timezone.utc),
    )
    written, release = asyncio.Event(), asyncio.Event()

    async def writer():
        async with env["transactions"].transaction() as db:
            await env["checkout_repo"].accept_receipt(receipt, session=db)
            written.set()
            await release.wait()

    pending_writer = asyncio.create_task(writer())
    await written.wait()
    review = asyncio.create_task(
        env["checkout"].review_authorization(
            auth["authorization_id"],
            CheckoutActor(
                env["admin"].user_id, "telegram", env["admin"].telegram_id
            ),
            "concurrent-review",
            version,
            "Actual provider support disposition reviewed",
            "case:race-reference",
        )
    )
    try:
        completed, _ = await asyncio.wait({review}, timeout=0.05)
        assert not completed
    finally:
        release.set()
        await pending_writer
    with pytest.raises(ValueError, match="paid_receipt_pending"):
        await review
