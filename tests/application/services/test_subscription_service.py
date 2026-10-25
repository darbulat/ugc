from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


class Transactions:
    @asynccontextmanager
    async def transaction(self):
        yield object()


class Repository:
    def __init__(self):
        self.rows = []
        self.uses = ()
        self.admin = uuid4()
        self.members = {uuid4() for _ in range(3)}

    async def context(self, actor_id, member_id, *, session):
        return dict(
            actor_active=True,
            admin=actor_id == self.admin,
            member_active=member_id in self.members or member_id == self.admin,
            manager=member_id in self.members,
        )

    async def lock(self, *, session):
        pass

    async def events(self, *, session):
        return list(self.rows)

    async def pilot_reuse(self, first_paid, *, session):
        return self.uses

    async def append(self, event, *, session):
        self.rows.append(event)


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 25, tzinfo=timezone.utc)

    def now(self):
        return self.at


@pytest.fixture
def env():
    from ugc_bot.application.services.subscription_service import (
        SubscriptionService,
    )

    repo, clock = Repository(), Clock()
    return SubscriptionService(repo, Transactions(), clock), repo, clock


async def publish(env):
    service, repo, _ = env
    return await service.execute(
        repo.admin,
        "publish",
        "tariff",
        dict(
            version="v1",
            title="Manager",
            price_minor=10000,
            duration_days=30,
            campaign_limit=5,
            recipient_limit=100,
            terms_reference="terms:v1",
            reason="publish agreed tariff",
        ),
    )


async def pay(env, member, reference, **changes):
    service, repo, clock = env
    return await service.execute(
        repo.admin,
        "accept_payment",
        reference,
        dict(
            member_id=str(member),
            tariff_version="v1",
            amount_minor=10000,
            currency="RUB",
            paid_at=clock.at.isoformat(),
            payment_reference=reference,
            evidence_reference="reviewed bank statement",
            evidence_hash="a" * 64,
            reason="verified actual receipt",
            pilot=True,
        )
        | changes,
    )


@pytest.mark.asyncio
async def test_payment_is_reviewed_idempotent_and_never_an_income_balance(env):
    service, repo, clock = env
    await publish(env)
    member = next(iter(repo.members))
    payment = await pay(env, member, "bank:one")
    assert await pay(env, member, "bank:one") == payment
    view = await service.view(member)
    assert view["subscription"]["state"] == "active"
    assert (
        view["subscription"]["until"]
        == (clock.at + timedelta(days=30)).isoformat()
    )
    assert view["subscription"]["scope"] == "own_consented_network"
    assert len(repo.rows) == 2
    assert "balance" not in view


@pytest.mark.asyncio
async def test_owner_cannot_publish_or_accept_fake_payment(env):
    service, repo, _ = env
    member = next(iter(repo.members))
    with pytest.raises(PermissionError):
        await service.execute(member, "publish", "fake", {})
    await publish(env)
    with pytest.raises(PermissionError):
        await service.execute(
            member, "accept_payment", "fake", dict(member_id=str(member))
        )
    assert len(repo.rows) == 1


@pytest.mark.asyncio
async def test_distinct_payment_references_and_exact_funding_are_required(env):
    await publish(env)
    members = list(env[1].members)
    await pay(env, members[0], "unique")
    with pytest.raises(ValueError, match="payment_reference"):
        await pay(
            env, members[1], "unique-second-command", payment_reference="unique"
        )
    with pytest.raises(ValueError, match="amount"):
        await pay(env, members[1], "underpaid", amount_minor=9999)
    with pytest.raises(ValueError, match="idempotency"):
        await pay(env, members[0], "unique", reason="changed proof")


@pytest.mark.asyncio
async def test_expiry_cancel_and_paid_renewal_have_no_automatic_charge(env):
    service, repo, clock = env
    await publish(env)
    member = next(iter(repo.members))
    await pay(env, member, "first")
    await pay(env, member, "renewal")
    assert (await service.view(member))["subscription"]["until"] == (
        clock.at + timedelta(days=60)
    ).isoformat()
    await service.execute(
        member, "cancel", "cancel", dict(reason="stop access")
    )
    assert (await service.view(member))["subscription"]["state"] == "cancelled"
    await pay(env, member, "restart")
    clock.at += timedelta(days=30)
    assert (await service.view(member))["subscription"]["state"] == "expired"


@pytest.mark.asyncio
async def test_automation_requires_three_real_paid_pilots_and_reuse(env):
    service, repo, _ = env
    await publish(env)
    payload = dict(
        reason="reviewed pilots",
        evidence_reference="pilot-review",
        evidence_hash="b" * 64,
    )
    with pytest.raises(ValueError, match="pilots"):
        await service.execute(repo.admin, "enable_automation", "early", payload)
    for index, member in enumerate(repo.members):
        await pay(env, member, f"pilot:{index}")
    with pytest.raises(ValueError, match="reuse"):
        await service.execute(
            repo.admin, "enable_automation", "no-reuse", payload
        )
    member = next(iter(repo.members))
    await pay(env, member, "renewal")
    with pytest.raises(ValueError, match="reuse"):
        await service.execute(
            repo.admin, "enable_automation", "renewal-only", payload
        )
    from ugc_bot.application.subscription_ports import SubscriptionCampaignUse

    repo.uses = (
        SubscriptionCampaignUse(member, uuid4(), uuid4()),
        SubscriptionCampaignUse(member, uuid4(), uuid4()),
    )
    result = await service.execute(
        repo.admin, "enable_automation", "review", payload
    )
    assert result["automation_enabled"] is True
    assert result["paid_pilot_managers"] == 3
    assert len(result["reuse_evidence"]) == 2
    assert {row["member_id"] for row in result["reuse_evidence"]} == {
        str(member)
    }
