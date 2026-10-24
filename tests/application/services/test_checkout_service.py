"""Trusted checkout transactions and native provider boundaries."""

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ugc_bot.application.services.checkout_service import CheckoutService
from ugc_bot.domain.checkout import CheckoutActor, PreparedInvoice, invoice_url


@pytest.mark.parametrize(
    "url",
    [
        "http://t.me/$slug",
        "https://t.me.evil.test/$slug",
        "https://evil.test/invoice/slug",
        "https://user@t.me/$slug",
        "https://t.me:444/$slug",
        "https://t.me/$slug?redirect=evil",
        "https://t.me/$slug#fragment",
        "https://t.me/bot?start=pay",
        "https://t.me/invoice/a%2fb",
        "https://t.me/$",
        "https://t.me/\\evil",
        "https://t.me/$slug\n",
    ],
)
def test_provider_invoice_url_is_a_strict_invoice_link(url):
    with pytest.raises(ValueError):
        invoice_url(url)


@pytest.mark.parametrize(
    "url", ["https://t.me/$Actual_slug-1", "https://t.me/invoice/Actual_slug-1"]
)
def test_actual_invoice_link_forms_are_preserved(url):
    assert invoice_url(url) == url


class Transactions:
    def __init__(self):
        self.active = 0

    @asynccontextmanager
    async def transaction(self):
        self.active += 1
        try:
            yield object()
        finally:
            self.active -= 1


def setup():
    tx = Transactions()
    actor = CheckoutActor(uuid4(), "telegram", "1001")
    prepared = PreparedInvoice(
        uuid4(), uuid4(), "RUB", 1500000, 120000, "Real brief"
    )
    result = {"invoice_state": "ready", "invoice_url": "https://t.me/$real"}
    repository = SimpleNamespace(
        prepare=AsyncMock(return_value=prepared),
        complete=AsyncMock(return_value=result),
        status=AsyncMock(return_value=result),
    )
    gateway = SimpleNamespace(create_link=AsyncMock())
    service = CheckoutService(repository, tx, gateway, True, True)
    return service, repository, gateway, tx, actor, prepared, result


@pytest.mark.asyncio
async def test_provider_call_is_once_between_committed_transactions():
    service, repo, gateway, tx, actor, prepared, result = setup()

    async def create(value):
        assert tx.active == 0
        assert value == prepared
        return "https://t.me/$real"

    gateway.create_link.side_effect = create
    assert (
        await service.request_invoice(prepared.order_id, actor, "same-key")
        == result
    )
    assert tx.active == 0
    assert gateway.create_link.await_count == 1
    assert repo.complete.await_args.kwargs["url"] == "https://t.me/$real"


@pytest.mark.asyncio
async def test_unknown_link_creation_is_recorded_without_automatic_retry():
    service, repo, gateway, tx, actor, prepared, _ = setup()
    gateway.create_link.side_effect = TimeoutError("synthetic uncertain send")
    repo.complete.return_value = {"invoice_state": "unknown"}
    assert await service.request_invoice(prepared.order_id, actor, "key") == {
        "invoice_state": "unknown"
    }
    assert gateway.create_link.await_count == 1
    assert repo.complete.await_args.kwargs["outcome"] == "unknown"
    assert tx.active == 0


@pytest.mark.asyncio
async def test_stored_replay_avoids_gateway_even_when_sales_paused():
    service, repo, gateway, _, actor, prepared, result = setup()
    repo.prepare.return_value = result
    service = replace(service, core_enabled=False, new_orders_enabled=False)
    assert (
        await service.request_invoice(prepared.order_id, actor, "key") == result
    )
    gateway.create_link.assert_not_awaited()
    assert not repo.prepare.await_args.kwargs["allow_new"]


@pytest.mark.asyncio
async def test_max_cannot_create_a_telegram_invoice_from_equal_numeric_id():
    service, repo, gateway, _, actor, prepared, _ = setup()
    with pytest.raises(PermissionError, match="telegram_checkout_required"):
        await service.request_invoice(
            prepared.order_id, replace(actor, platform="max"), "key"
        )
    repo.prepare.assert_not_awaited()
    gateway.create_link.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_gateway", [True, False])
async def test_definite_gateway_rejection_is_recorded_as_failed(
    missing_gateway,
):
    from ugc_bot.domain.checkout import LinkRejected

    service, repo, gateway, _, actor, prepared, _ = setup()
    if missing_gateway:
        service = replace(service, gateway=None)
    else:
        gateway.create_link.side_effect = LinkRejected(
            "definite provider rejection"
        )
    await service.request_invoice(prepared.order_id, actor, "key")
    assert repo.complete.await_args.kwargs["outcome"] == "failed"


@pytest.mark.asyncio
async def test_authorization_service_owns_its_transaction():
    service, repo, _, tx, actor, prepared, _ = setup()

    async def authorize(*args, session, allow_new):
        assert tx.active == 1
        assert allow_new
        return {"authorization_id": "actual"}

    repo.authorize = authorize
    assert await service.authorize(
        prepared.order_id, actor.external_id, "native-query", 50000, "RUB"
    ) == {"authorization_id": "actual"}
    assert tx.active == 0
