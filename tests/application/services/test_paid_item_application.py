"""Ported quotes: validated snapshots, opaque caller transaction."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ugc_bot.application.services import paid_item_service as module
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
    FinancialPolicyService,
)
from ugc_bot.config import FinancialConfig


def parameters():
    now = datetime.now(timezone.utc)
    client = uuid4()
    policy = FinancialPolicy(
        "v1",
        uuid4(),
        now,
        now,
        timedelta(days=2),
        frozenset({client}),
        "terms:v1",
    )
    return dict(
        policy=policy,
        client_id=client,
        order_created_at=now,
        selection_due_at=now + timedelta(days=3),
        currency="RUB",
        now=now,
        order_id=uuid4(),
        accompaniment_ordinals=frozenset({1, 3}),
        client_contact_reference="protected:client",
        idempotency_key="new-1",
    )


class QuoteStore:
    def __init__(self):
        self.saved = []

    async def save_quote(self, quote, *, session):
        self.saved.append((quote, session))
        return quote


@pytest.mark.asyncio
async def test_service_persists_standard_quote_through_opaque_port():
    assert hasattr(module, "PaidItemService"), "application service missing"
    store = QuoteStore()
    service = module.PaidItemService(
        store,
        FinancialPolicyService(
            FinancialConfig(
                FINANCIAL_CORE_ENABLED=True, FINANCIAL_NEW_ORDERS_ENABLED=True
            )
        ),
    )
    session = object()
    quote = await service.quote_new_order(**parameters(), session=session)
    assert len(quote.items) == 30
    assert quote.selection_base_minor == 1500000
    assert quote.total_minor == 1740000
    assert store.saved == [(quote, session)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        "disabled",
        "policy",
        "approval",
        "allowlist",
        "refund",
        "terms",
        "deadline",
        "currency",
        "contact",
        "ordinal",
    ],
)
async def test_invalid_inputs_rejected_before_save(
    invalid,
):
    from dataclasses import replace

    store = QuoteStore()
    config = FinancialConfig(
        FINANCIAL_CORE_ENABLED=invalid != "disabled",
        FINANCIAL_NEW_ORDERS_ENABLED=True,
    )
    service = module.PaidItemService(store, FinancialPolicyService(config))
    params = parameters()
    if invalid == "policy":
        params["policy"] = None
    elif invalid in {"approval", "allowlist", "refund", "terms"}:
        field, value = {
            "approval": ("approved_at", None),
            "allowlist": ("allowed_clients", frozenset()),
            "refund": ("selection_refund_window", None),
            "terms": ("terms_reference", None),
        }[invalid]
        params["policy"] = replace(params["policy"], **{field: value})
    elif invalid == "deadline":
        params["selection_due_at"] = None
    elif invalid == "currency":
        params["currency"] = "USD"
    elif invalid == "contact":
        params["client_contact_reference"] = " "
    elif invalid == "ordinal":
        params["accompaniment_ordinals"] = frozenset({31})
    with pytest.raises(ValueError):
        await service.quote_new_order(**params, session=object())
    assert not store.saved


def test_override_and_nonstandard_price_are_not_exposed_by_quote_command():
    import inspect

    assert (
        "selection_minor"
        not in inspect.signature(
            module.PaidItemService.prepare_quote
        ).parameters
    )
    assert (
        "accompaniment_minor"
        not in inspect.signature(
            module.PaidItemService.prepare_quote
        ).parameters
    )
    gate = FinancialPolicyService(FinancialConfig())
    for method in (
        gate.create_override,
        gate.apply_override,
        gate.set_nonstandard_price,
    ):
        with pytest.raises(ValueError, match="policy_feature_disabled"):
            method()


@pytest.mark.asyncio
async def test_legacy_creation_never_uses_opt_in_service(
    user_repo, advertiser_repo, order_repo
):
    from tests.helpers.factories import create_test_advertiser
    from tests.helpers.services import build_order_service
    from ugc_bot.domain.enums import OrderType

    client = await create_test_advertiser(user_repo, advertiser_repo)
    service = build_order_service(user_repo, advertiser_repo, order_repo)

    class ForbiddenFinancialService:
        def prepare_quote(self, **kwargs):
            raise AssertionError("legacy autoactivation")

    service.paid_item_service = ForbiddenFinancialService()
    order = await service.create_order(
        advertiser_id=client,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="legacy",
        barter_description=None,
        price=1000,
        bloggers_needed=3,
    )
    assert order.bloggers_needed == 3
    assert await order_repo.get_by_id(order.order_id) == order
