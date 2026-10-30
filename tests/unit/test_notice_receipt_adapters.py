"""One-shot provider adapters preserve actual references and uncertainty."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.application.services.test_collaboration_notice_delivery import (
    event_id,
    setup_delivery,
)
from ugc_bot.application.notice_delivery_ports import DeliveryFailure


def adapters():
    try:
        from ugc_bot.infrastructure.messenger.notice_receipts import (
            MaxNoticeReceipts,
            RoutedNoticeReceipts,
            TelegramNoticeReceipts,
        )
    except ModuleNotFoundError:
        pytest.fail("One-shot receipt adapters are missing")
    return TelegramNoticeReceipts, MaxNoticeReceipts, RoutedNoticeReceipts


async def prepared():
    worker, _, repo, *_ = await setup_delivery()
    # Receipt semantics also apply to plain messages from nonfinancial owners.
    return replace(
        await worker.prepare(event_id(repo)), action_url=None, action_label=None
    )


@pytest.mark.asyncio
async def test_telegram_returns_actual_chat_message_id_without_retry():
    Telegram, _, _ = adapters()
    bot = SimpleNamespace(
        send_message=AsyncMock(
            return_value=SimpleNamespace(
                message_id=42, chat=SimpleNamespace(id=101)
            )
        )
    )
    attempt = await prepared()
    result = await Telegram(bot).send(attempt)
    assert result.channel == "telegram" and result.reference == "101:42"
    bot.send_message.assert_awaited_once_with(
        chat_id=101, text=attempt.text, parse_mode=None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,uncertain",
    [
        ("rejected", False),
        ("network", True),
        ("missing", True),
        ("wrong_chat", True),
    ],
)
async def test_telegram_errors_and_missing_reference_do_not_retry(
    failure, uncertain
):
    from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
    from aiogram.methods import SendMessage

    Telegram, _, _ = adapters()
    method = SendMessage(chat_id=101, text="synthetic")
    bot = SimpleNamespace(send_message=AsyncMock())
    if failure in ("rejected", "network"):
        cls = (
            TelegramBadRequest
            if failure == "rejected"
            else TelegramNetworkError
        )
        bot.send_message.side_effect = cls(method=method, message="synthetic")
    else:
        bot.send_message.return_value = SimpleNamespace(
            message_id=None if failure == "missing" else 42,
            chat=SimpleNamespace(id=999 if failure == "wrong_chat" else 101),
        )
    with pytest.raises(DeliveryFailure) as error:
        await Telegram(bot).send(await prepared())
    assert error.value.uncertain is uncertain
    assert bot.send_message.await_count == 1


class Response:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.payload


class MaxSession:
    def __init__(self, status=200, payload=None):
        self.response = Response(
            status, payload or {"message": {"body": {"mid": "mid.actual.12"}}}
        )
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat_id", "user_id"])
async def test_max_posts_once_to_official_endpoint_and_returns_body_mid(kind):
    _, Max, _ = adapters()
    session = MaxSession()
    attempt = replace(
        await prepared(), channel="max", address="202", address_kind=kind
    )
    receipt = await Max(session, "synthetic-token").send(attempt)
    assert receipt.channel == "max" and receipt.reference == "mid.actual.12"
    assert len(session.calls) == 1
    url, request = session.calls[0]
    assert url == "https://platform-api2.max.ru/messages"
    assert request["params"] == {kind: 202}
    assert request["headers"] == {"Authorization": "synthetic-token"}
    assert request["json"] == {"text": attempt.text}
    assert request["timeout"].total == 30


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload,uncertain",
    [
        (403, {"code": "bot.blocked"}, False),
        (429, {"code": "rate.limit"}, False),
        (503, {"code": "unavailable"}, True),
        (200, {"success": True}, True),
    ],
)
async def test_max_rejection_unknown_and_missing_mid_are_never_auto_retried(
    status, payload, uncertain
):
    _, Max, _ = adapters()
    session = MaxSession(status, payload)
    with pytest.raises(DeliveryFailure) as error:
        await Max(session, "synthetic-token").send(
            replace(await prepared(), channel="max")
        )
    assert error.value.uncertain is uncertain
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_route_without_supported_receipt_transport_fails_before_io():
    _, _, Routed = adapters()
    with pytest.raises(DeliveryFailure) as error:
        await Routed({}).send(await prepared())
    assert not error.value.uncertain


@pytest.mark.asyncio
@pytest.mark.parametrize("address", [None, "not-a-number", "0"])
async def test_invalid_authoritative_address_fails_before_provider_call(
    address,
):
    Telegram, _, _ = adapters()
    bot = SimpleNamespace(send_message=AsyncMock())
    with pytest.raises(DeliveryFailure) as error:
        await Telegram(bot).send(replace(await prepared(), address=address))
    assert not error.value.uncertain and not bot.send_message.called


@pytest.mark.asyncio
async def test_max_without_token_is_explicitly_unavailable_before_io():
    _, Max, _ = adapters()
    session = MaxSession()
    with pytest.raises(DeliveryFailure) as error:
        await Max(session, "").send(replace(await prepared(), channel="max"))
    assert not error.value.uncertain and not session.calls


@pytest.mark.asyncio
async def test_max_network_exception_is_unknown_with_one_request():
    _, Max, _ = adapters()

    class BrokenSession(MaxSession):
        def post(self, url, **kwargs):
            super().post(url, **kwargs)
            raise TimeoutError("synthetic timeout; acceptance unknown")

    session = BrokenSession()
    with pytest.raises(DeliveryFailure) as error:
        await Max(session, "synthetic-token").send(
            replace(await prepared(), channel="max")
        )
    assert error.value.uncertain and len(session.calls) == 1


@pytest.mark.asyncio
async def test_routed_supported_transport_preserves_actual_receipt():
    Telegram, _, Routed = adapters()
    bot = SimpleNamespace(
        send_message=AsyncMock(
            return_value=SimpleNamespace(
                message_id=19, chat=SimpleNamespace(id=101)
            )
        )
    )
    receipt = await Routed({"telegram": Telegram(bot)}).send(await prepared())
    assert receipt.reference == "101:19" and bot.send_message.await_count == 1


@pytest.mark.asyncio
async def test_rate_limits_report_delay_without_inline_retry():
    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import SendMessage

    Telegram, Max, _ = adapters()
    bot = SimpleNamespace(
        send_message=AsyncMock(
            side_effect=TelegramRetryAfter(
                method=SendMessage(chat_id=101, text="test"),
                message="limited",
                retry_after=75,
            )
        )
    )
    with pytest.raises(DeliveryFailure) as telegram:
        await Telegram(bot).send(await prepared())
    assert telegram.value.uncertain is False
    assert telegram.value.retry_after_seconds == 75
    assert bot.send_message.await_count == 1

    session = MaxSession(429, {"code": "rate.limit"})
    session.response.headers = {"Retry-After": "90"}
    with pytest.raises(DeliveryFailure) as max_error:
        await Max(session, "synthetic-token").send(
            replace(await prepared(), channel="max")
        )
    assert max_error.value.uncertain is False
    assert max_error.value.retry_after_seconds == 90
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_max_http_date_rate_limit_waits_until_requested_time(monkeypatch):
    from datetime import datetime, timezone
    from email.utils import format_datetime

    from ugc_bot.infrastructure.messenger import notice_receipts

    now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(
        notice_receipts, "datetime", FixedDateTime, raising=False
    )
    _, Max, _ = adapters()
    session = MaxSession(429, {"code": "rate.limit"})
    session.response.headers = {
        "Retry-After": format_datetime(now.replace(minute=2), usegmt=True)
    }
    with pytest.raises(DeliveryFailure) as error:
        await Max(session, "synthetic-token").send(
            replace(await prepared(), channel="max")
        )
    assert error.value.retry_after_seconds == 120
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_max_malformed_retry_after_does_not_retry_early():
    _, Max, _ = adapters()
    session = MaxSession(429, {"code": "rate.limit"})
    session.response.headers = {"Retry-After": "not a valid delay"}
    with pytest.raises(DeliveryFailure) as error:
        await Max(session, "synthetic-token").send(
            replace(await prepared(), channel="max")
        )
    assert error.value.uncertain is False
    assert error.value.retry_after_seconds is None
