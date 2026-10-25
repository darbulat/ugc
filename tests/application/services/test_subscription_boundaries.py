"""Paid periods, proof, pilot evidence and current-role boundary conditions."""

from datetime import timedelta
from uuid import uuid4

import pytest

from tests.application.services.test_subscription_service import (
    env as subscription_env_fixture,
)
from tests.application.services.test_subscription_service import (
    pay,
    publish,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.subscription_service import state
from ugc_bot.application.subscription_ports import SubscriptionCampaignUse

env = subscription_env_fixture


@pytest.mark.asyncio
async def test_tariff_version_and_unknown_or_extra_fields_are_refused(env):
    service, repo, _ = env
    with pytest.raises(ValueError, match="unknown_action"):
        await service.execute(repo.admin, "other", "key", {})
    with pytest.raises(ValueError, match="unexpected_fields"):
        await service.execute(
            repo.admin, "publish", "key", {"reason": "publish"}
        )
    await publish(env)
    payload = dict(repo.rows[0]["payload"], price_minor=20000)
    with pytest.raises(ValueError, match="tariff_version_immutable"):
        await service.execute(repo.admin, "publish", "new-key", payload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,error",
    [
        (dict(amount_minor=True), "exact_tariff_amount"),
        (dict(currency="USD"), "exact_tariff_amount"),
        (dict(pilot=1), "pilot_boolean"),
        (dict(evidence_hash="A" * 64), "evidence_hash"),
        (dict(evidence_reference=" "), "provenance"),
        (dict(payment_reference=" "), "provenance"),
        (dict(tariff_version="unpublished"), "published_tariff"),
        (dict(paid_at="2027-01-01T00:00:00+00:00"), "future_payment"),
    ],
)
async def test_manual_payment_requires_actual_matching_tariff_and_proof(
    env, changes, error
):
    await publish(env)
    with pytest.raises(ValueError, match=error):
        await pay(env, next(iter(env[1].members)), "invalid", **changes)
    assert len(env[1].rows) == 1


@pytest.mark.asyncio
async def test_inactive_member_is_not_funded_and_inactive_actor_cannot_replay(
    env,
):
    service, repo, _ = env
    await publish(env)
    with pytest.raises(PermissionError, match="active_manager"):
        await pay(env, uuid4(), "not-a-manager")
    original_context = repo.context

    async def context(*args, **kwargs):
        return dict(await original_context(*args, **kwargs), actor_active=False)

    repo.context = context
    with pytest.raises(PermissionError, match="active_account"):
        await publish(env)


@pytest.mark.asyncio
async def test_current_native_owner_required_even_for_existing_receipt(env):
    service, repo, _ = env
    await publish(env)
    native = "old-native"
    original_context = repo.context

    async def context(*args, **kwargs):
        return dict(await original_context(*args, **kwargs), telegram_id=native)

    repo.context = context
    proof = AuthenticatedMessengerPrincipal(repo.admin, "telegram", native)
    payload = dict(repo.rows[0]["payload"])
    assert (
        await service.execute(
            repo.admin, "publish", "tariff", payload, principal=proof
        )
        == repo.rows[0]["result"]
    )
    native = "new-native"
    with pytest.raises(ValueError, match="financial_principal_changed"):
        await service.execute(
            repo.admin, "publish", "tariff", payload, principal=proof
        )


@pytest.mark.asyncio
async def test_unpaid_cancel_rejected_and_member_view_has_no_foreign_evidence(
    env,
):
    service, repo, _ = env
    member, other = list(repo.members)[:2]
    assert state([], member, env[2].at)["state"] == "unpaid"
    with pytest.raises(ValueError, match="active_period_required"):
        await service.execute(
            member, "cancel", "cancel-unpaid", dict(reason="stop")
        )
    await publish(env)
    await pay(env, other, "PRIVATE FOREIGN BANK REFERENCE")
    view = await service.view(member)
    assert view["subscription"]["state"] == "unpaid"
    assert "PRIVATE" not in str(view) and "payments" not in view
    admin = await service.view(repo.admin)
    assert (
        admin["payments"][0]["payment_reference"]
        == "PRIVATE FOREIGN BANK REFERENCE"
    )


@pytest.mark.asyncio
async def test_prepaid_new_tariff_does_not_change_current_period_limits(env):
    service, repo, clock = env
    await publish(env)
    member = next(iter(repo.members))
    await pay(env, member, "period-1")
    payload = dict(repo.rows[0]["payload"], version="v2", campaign_limit=10)
    await service.execute(repo.admin, "publish", "tariff-2", payload)
    await pay(env, member, "period-2", tariff_version="v2")
    current = (await service.view(member))["subscription"]
    assert current["campaign_limit"] == 5 and current["tariff_version"] == "v1"
    assert current["until"] == (clock.at + timedelta(days=60)).isoformat()
    assert (
        current["period_until"] == (clock.at + timedelta(days=30)).isoformat()
    )
    clock.at += timedelta(days=30)
    current = (await service.view(member))["subscription"]
    assert current["campaign_limit"] == 10 and current["tariff_version"] == "v2"


@pytest.mark.asyncio
async def test_pilot_reuse_must_be_two_distinct_owned_campaigns(env):
    service, repo, _ = env
    await publish(env)
    members = list(repo.members)
    for i, member in enumerate(members):
        await pay(env, member, "pilot:" + str(i))
    campaign = uuid4()
    repo.uses = (
        SubscriptionCampaignUse(members[0], campaign, uuid4()),
        SubscriptionCampaignUse(members[0], campaign, uuid4()),
        SubscriptionCampaignUse(uuid4(), uuid4(), uuid4()),
    )
    payload = dict(
        reason="review",
        evidence_reference="actual-pilot-review",
        evidence_hash="b" * 64,
    )
    with pytest.raises(ValueError, match="actual_paid_reuse"):
        await service.execute(
            repo.admin, "enable_automation", "review", payload
        )
    with pytest.raises(ValueError, match="pilot_evidence"):
        service._apply(
            "enable_automation", repo.admin, {}, payload, [], env[2].at
        )
