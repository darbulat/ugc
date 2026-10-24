"""Trusted checkout transactions and native provider boundaries."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from tests.application.services.test_checkout_service import setup
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.application.services.checkout_paid_notices import (
    PaidNotice,
    PaidNoticeDelivery,
)
from ugc_bot.application.services.checkout_paid_receipts import (
    PaidReceiptProcessor,
    native_receipt,
)
from ugc_bot.checkout_runtime import (
    _work,
    register_checkout_lifecycle,
    start_checkout_runtime,
    stop_checkout_runtime,
)
from ugc_bot.domain.checkout import NativePaidReceipt


@pytest.mark.asyncio
async def test_runtime_default_off_registers_durable_ingress_without_task():
    checkout, *_ = setup()
    dispatcher = {"checkout_service": checkout, "payment_service": object()}
    config = SimpleNamespace(
        bot=SimpleNamespace(telegram_payment_account_id="")
    )
    assert start_checkout_runtime(dispatcher, object(), config) is None
    assert isinstance(
        dispatcher["checkout_paid_processor"], PaidReceiptProcessor
    )
    assert "checkout_worker_task" not in dispatcher
    await stop_checkout_runtime(dispatcher)
    assert start_checkout_runtime({}, None, config) is None


@pytest.mark.asyncio
async def test_configured_runtime_lifecycle_runs_recovers_and_cancels(
    monkeypatch,
):
    import ugc_bot.checkout_runtime as runtime

    checkout, repo, *_ = setup()
    repo.claim_receipt = AsyncMock(
        side_effect=[RuntimeError("transient"), None]
    )
    repo.claim_notice = AsyncMock(return_value=None)
    dispatcher = type("Dispatcher", (dict,), {})(
        {"checkout_service": checkout, "payment_service": object()}
    )
    dispatcher.startup = SimpleNamespace(register=Mock())
    dispatcher.shutdown = SimpleNamespace(register=Mock())
    config = SimpleNamespace(
        bot=SimpleNamespace(telegram_payment_account_id="actual-account")
    )
    sleeping = asyncio.Event()

    async def sleep(_):
        sleeping.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime.asyncio, "sleep", sleep)
    register_checkout_lifecycle(dispatcher, config)
    await dispatcher.startup.register.call_args.args[0](object())
    await asyncio.wait_for(sleeping.wait(), 1)
    assert repo.claim_receipt.await_count == 1
    await dispatcher.shutdown.register.call_args.args[0]()
    assert dispatcher["checkout_worker_task"] is None


@pytest.mark.asyncio
async def test_worker_drains_both_jobs_before_idle_wait(monkeypatch):
    import ugc_bot.checkout_runtime as runtime

    processor = SimpleNamespace(run_once=AsyncMock(return_value=True))
    notices = SimpleNamespace(run_once=AsyncMock(return_value=False))

    async def stop(delay):
        assert delay == 0.1
        raise asyncio.CancelledError

    monkeypatch.setattr(runtime.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        await _work(processor, notices)
    processor.run_once.assert_awaited_once()
    notices.run_once.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "known_failure",
        "unknown",
        "invalid_receipt",
        "exception",
        "accepted",
        "empty",
    ],
)
async def test_notice_outcomes_do_not_reenter_or_recalculate_payment(case):
    from tests.application.services.test_checkout_service import Transactions

    notice = PaidNotice(
        uuid4(), uuid4(), "telegram", "123", "Actual confirmed payment"
    )
    repo = SimpleNamespace(
        claim_notice=AsyncMock(
            return_value=None if case == "empty" else notice
        ),
        finish_notice=AsyncMock(),
    )
    transport = SimpleNamespace(
        send=AsyncMock(return_value=DeliveryReceipt("telegram", "actual-id"))
    )
    if case in {"known_failure", "unknown"}:
        transport.send.side_effect = DeliveryFailure(
            "provider-result", uncertain=case == "unknown"
        )
    elif case == "invalid_receipt":
        transport.send.return_value = DeliveryReceipt("max", "")
    elif case == "exception":
        transport.send.side_effect = RuntimeError("network")
    delivery = PaidNoticeDelivery(repo, Transactions(), transport)
    assert await delivery.run_once() == (case != "empty")
    if case == "empty":
        transport.send.assert_not_awaited()
        return
    assert repo.finish_notice.await_args.args[1] == (
        "failed"
        if case == "known_failure"
        else "accepted"
        if case == "accepted"
        else "unknown"
    )


@pytest.mark.asyncio
async def test_missing_native_payer_remains_unresolved_and_no_capture():
    from tests.application.services.test_checkout_service import Transactions

    native = NativePaidReceipt(
        "missing",
        "chat",
        "msg",
        uuid4(),
        "provider",
        "telegram",
        100,
        "RUB",
        datetime.now(timezone.utc),
    )
    claim = {"receipt": native, "client_id": None}
    repo = SimpleNamespace(
        claim_receipt=AsyncMock(return_value=claim), finish_receipt=AsyncMock()
    )
    payments = SimpleNamespace(confirm_telegram_payment=AsyncMock())
    assert await PaidReceiptProcessor(repo, Transactions(), payments).run_once()
    payments.confirm_telegram_payment.assert_not_awaited()
    assert repo.finish_receipt.await_args.args[1] == "unresolved"
    with pytest.raises(ValueError):
        native_receipt(SimpleNamespace(successful_payment=None))
    with pytest.raises(ValueError):
        native_receipt(
            SimpleNamespace(
                successful_payment=SimpleNamespace(protocol_message_at=None)
            )
        )
