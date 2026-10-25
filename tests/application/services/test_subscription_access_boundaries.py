"""Campaign access uses paid current periods and actual campaign usage."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from tests.application.services.test_subscription_service import (
    env as subscription_env_fixture,
)
from tests.application.services.test_subscription_service import (
    pay,
    publish,
)
from ugc_bot.application.services.subscription_campaign_access import (
    SubscriptionCampaignAccess,
)
from ugc_bot.container.subscription_factory import build_subscription_access

env = subscription_env_fixture


class Usage:
    def __init__(self, submissions=0, attempts=0):
        self.totals = submissions, attempts
        self.calls = []

    async def usage(self, owner_id, starts_at, *, session):
        self.calls.append((owner_id, starts_at))
        return self.totals


async def enabled(env):
    _, repo, _ = env
    await publish(env)
    member = next(iter(repo.members))
    await pay(env, member, "paid-period")
    # Automation evidence is independently tested by the service; access reads
    # only its immutable approved event, never infers it from payment alone.
    repo.rows.append(
        dict(
            action="enable_automation",
            member_id=str(repo.admin),
            actor_id=str(repo.admin),
            operation_key="approved-automation",
            sequence=len(repo.rows) + 1,
        )
    )
    return member


@pytest.mark.asyncio
async def test_paid_subscription_without_automation_or_foreign_owner_is_denied(
    env,
):
    _, repo, clock = env
    await publish(env)
    member, foreign = list(repo.members)[:2]
    await pay(env, member, "paid")
    usage = Usage()
    access = SubscriptionCampaignAccess(repo, usage)
    with pytest.raises(PermissionError, match="subscription_required"):
        await access.require_access(
            member, action="submit", at=clock.at, session=object()
        )
    repo.rows.append(
        dict(action="enable_automation", member_id=str(repo.admin))
    )
    with pytest.raises(PermissionError, match="subscription_required"):
        await access.require_access(
            foreign, action="send", at=clock.at, session=object()
        )
    assert usage.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,submissions,attempts,allowed",
    [
        ("submit", 4, 1000, True),
        ("submit", 5, 0, False),
        ("send", 99, 99, True),
        ("send", 0, 100, False),
    ],
)
async def test_exact_quota_boundaries_use_the_correct_actual_usage(
    env, action, submissions, attempts, allowed
):
    member = await enabled(env)
    usage = Usage(submissions, attempts)
    access = SubscriptionCampaignAccess(env[1], usage)
    if allowed:
        await access.require_access(
            member, action=action, at=env[2].at, session=object()
        )
    else:
        with pytest.raises(PermissionError, match="quota_exceeded"):
            await access.require_access(
                member, action=action, at=env[2].at, session=object()
            )
    assert usage.calls == [(member, env[2].at)]


@pytest.mark.asyncio
async def test_expired_and_cancelled_periods_do_not_query_usage(env):
    member = await enabled(env)
    usage = Usage()
    access = SubscriptionCampaignAccess(env[1], usage)
    with pytest.raises(PermissionError, match="subscription_required"):
        await access.require_access(
            member,
            action="send",
            at=env[2].at + timedelta(days=30),
            session=object(),
        )
    await env[0].execute(member, "cancel", "cancel", dict(reason="stop"))
    with pytest.raises(PermissionError, match="subscription_required"):
        await access.require_access(
            member, action="send", at=env[2].at, session=object()
        )
    assert usage.calls == []


def test_factory_keeps_paid_gate_opt_in():
    assert (
        build_subscription_access(
            SimpleNamespace(
                campaign=SimpleNamespace(require_paid_subscription=False)
            )
        )
        is None
    )
    access = build_subscription_access(
        SimpleNamespace(
            campaign=SimpleNamespace(require_paid_subscription=True)
        )
    )
    assert isinstance(access, SubscriptionCampaignAccess)
