"""Public native proof at the existing intake barrier; synthetic memory only."""

from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import fields, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4, uuid5

import pytest

from tests.application.services.test_financial_policy_service import (
    ready_policy,
)
from tests.application.services.test_order_intake_service import values
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.order_intake_service import OrderIntakeService
from ugc_bot.domain.order_intake import IntakeClient, OrderIntakeCommand


class IntakeFacts:
    def __init__(self, client):
        self.client = client
        self.calls = []
        self.receipt = None
        self.versions = ()
        self.policy = None
        self.orders = []
        self.quotes = []
        self.leads = []

    @asynccontextmanager
    async def transaction(self):
        saved = deepcopy((self.receipt, self.orders, self.quotes, self.leads))
        try:
            yield self
        except BaseException:
            self.receipt, self.orders, self.quotes, self.leads = saved
            raise

    async def lock_client(self, client_id, *, session):
        self.calls.append("client")
        return self.client

    async def policy_versions(self, at, *, session):
        self.calls.append("policies")
        return self.versions

    async def lock_operation(self, *args, **kwargs):
        self.calls.append("operation")

    async def get_receipt(self, client_id, operation_key, *, session):
        self.calls.append("receipt")
        return (
            self.receipt
            if getattr(self.receipt, "operation_key", operation_key)
            == operation_key
            else None
        )

    async def load(self, version, *, session):
        self.calls.append("policy")
        return self.policy

    async def create_financial_order(self, **values):
        self.calls.append("order_quote")
        self.orders.append(values["order_id"])
        quote = SimpleNamespace(
            order_id=values["order_id"],
            currency=values["currency"],
            policy_version=values["policy"].version,
            selection_due_at=values["selection_due_at"],
            terms_reference=values["policy"].terms_reference,
            items=tuple(
                SimpleNamespace(
                    paid_item_id=uuid5(values["order_id"], str(n)),
                    ordinal=n,
                    selection_minor=50000,
                    accompaniment_minor=120000
                    if n in values["accompaniment_ordinals"]
                    else 0,
                )
                for n in range(1, 31)
            ),
        )
        self.quotes.append(quote)
        return None, quote

    async def save(self, receipt, lead, *, session):
        self.calls.append("save")
        self.receipt = receipt
        if lead is not None:
            self.leads.append(lead)


def setup(platform):
    command = OrderIntakeCommand(**values())
    client = IntakeClient(command.client_id, "active", True, "RUB")
    facts = IntakeFacts(client)
    service = OrderIntakeService(
        facts,
        facts,
        facts,
        facts,
        SimpleNamespace(
            now=lambda: datetime(2026, 10, 24, tzinfo=timezone.utc)
        ),
        SimpleNamespace(core_enabled=True, new_orders_enabled=True),
    )
    principal = AuthenticatedMessengerPrincipal(
        command.client_id, platform, "123"
    )
    return service, facts, command, principal


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_intake_changed_binding_denies_policy_and_replay(platform):
    service, facts, command, principal = setup(platform)
    facts.receipt = SimpleNamespace(
        payload_hash=command.payload_hash, result="private"
    )
    for method, argument in (
        (service.eligible_policies, command.client_id),
        (service.create, command),
    ):
        facts.calls.clear()
        with pytest.raises(ValueError, match="financial_principal_changed"):
            await method(argument, principal=principal)
        assert facts.calls == ["client"]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_intake_native_bound_actor_succeeds(platform):
    service, facts, command, principal = setup(platform)
    facts.client = replace(facts.client, telegram_id="123", max_id="123")
    assert (
        await service.eligible_policies(command.client_id, principal=principal)
    ).currency == "RUB"
    facts.receipt = SimpleNamespace(
        payload_hash=command.payload_hash, result="same-owner"
    )
    assert await service.create(command, principal=principal) == "same-owner"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("missing", [False, True])
async def test_intake_uuid_mismatch_and_missing_mapping_deny_without_order(
    platform, missing
):
    service, facts, command, principal = setup(platform)
    if missing:
        facts.client = None
    else:
        principal = replace(principal, user_id=uuid4())
    with pytest.raises(ValueError, match="financial_principal_changed"):
        await service.create(command, principal=principal)
    assert facts.calls == ["client"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [{"status": "blocked"}, {"is_advertiser": False}]
)
async def test_intake_current_role_status_still_deny(change):
    service, facts, command, principal = setup("telegram")
    facts.client = replace(facts.client, telegram_id="123", **change)
    with pytest.raises(PermissionError, match="active_advertiser_required"):
        await service.create(command, principal=principal)
    assert facts.calls == ["client"]


def test_intake_auth_is_not_command_hash():
    _, _, command, _ = setup("telegram")
    assert not {"principal", "platform", "external_id"} & {
        f.name for f in fields(command)
    }
    assert replace(command).payload_hash == command.payload_hash


def ready(platform="telegram", *, managed=False):
    service, facts, command, principal = setup(platform)
    _, policy, _ = ready_policy()
    facts.client = replace(facts.client, telegram_id="123", max_id="456")
    facts.policy = replace(
        policy, allowed_clients=frozenset({command.client_id})
    )
    facts.versions = (facts.policy.version,)
    command = replace(
        command,
        policy_version=facts.policy.version,
        service_mode="with_manager" if managed else "self_service",
        accompaniment_ordinals=frozenset({1, 30}) if managed else frozenset(),
    )
    return service, facts, command, principal


@pytest.mark.asyncio
@pytest.mark.parametrize("managed", [False, True])
async def test_intake_real_memory_creation_and_cross_platform_receipt(managed):
    service, facts, command, proof = ready(managed=managed)
    first = await service.create(command, principal=proof)
    second = await service.create(
        command, principal=replace(proof, platform="max", external_id="456")
    )
    assert first == second
    assert len(facts.orders) == len(facts.quotes) == 1
    assert len(facts.leads) == int(managed)
    assert len(first.items) == 30
    assert facts.receipt.payload_hash == command.payload_hash
    snapshot = deepcopy(
        (facts.orders, facts.quotes, facts.leads, facts.receipt)
    )
    facts.client = replace(facts.client, telegram_id="remapped")
    for method, value in (
        (service.eligible_policies, command.client_id),
        (service.create, command),
    ):
        with pytest.raises(ValueError, match="financial_principal_changed"):
            await method(value, principal=proof)
    assert (facts.orders, facts.quotes, facts.leads, facts.receipt) == snapshot


@pytest.mark.asyncio
async def test_intake_policies_remain_current_and_bounded():
    service, facts, command, proof = ready()
    assert (
        len(
            (
                await service.eligible_policies(
                    command.client_id, principal=proof
                )
            ).policies
        )
        == 1
    )
    facts.policy = replace(facts.policy, allowed_clients=frozenset())
    assert not (
        await service.eligible_policies(command.client_id, principal=proof)
    ).policies
    facts.client = replace(facts.client, currency="")
    assert not (
        await service.eligible_policies(command.client_id, principal=proof)
    ).policies
    with pytest.raises(ValueError, match="unpublished_currency"):
        await service.create(command, principal=proof)
    assert not facts.orders and not facts.receipt


@pytest.mark.asyncio
async def test_intake_trusted_internal_and_disabled_paths_retain_contract():
    service, facts, command, _ = ready()
    facts.client = replace(facts.client, telegram_id=None, max_id=None)
    result = await service.create(command)
    assert await service.create(command) == result
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await service.create(replace(command, offer_text="changed"))
    service.config.new_orders_enabled = False
    assert await service.create(command) == result
    with pytest.raises(ValueError, match="financial_disabled"):
        await service.create(replace(command, operation_key="new"))
    assert (await service.eligible_policies(command.client_id)).writes_paused
    service.config.core_enabled = False
    with pytest.raises(ValueError, match="financial_disabled"):
        await service.create(command)
    facts.client = None
    with pytest.raises(PermissionError, match="active_advertiser_required"):
        await service.eligible_policies(command.client_id)
    assert len(facts.orders) == 1
