"""Funnel writes recheck the locked identity and current advertiser role."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from tests.application.services.test_native_intake import setup


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("invalid", ["missing", "blocked", "role", "binding"])
async def test_funnel_current_identity_and_role_before_any_event(
    platform, invalid
):
    service, facts, command, principal = setup(platform)
    facts.client = replace(facts.client, telegram_id="123", max_id="123")
    if invalid == "missing":
        facts.client = None
        # Internal callers also get a current-status check without HTTP proof.
        principal = None
    elif invalid == "blocked":
        facts.client = replace(facts.client, status="blocked")
    elif invalid == "role":
        facts.client = replace(facts.client, is_advertiser=False)
    else:
        facts.client = replace(
            facts.client, telegram_id="changed", max_id="changed"
        )
    error, reason = (
        (ValueError, "financial_principal_changed")
        if invalid == "binding"
        else (PermissionError, "active_advertiser_required")
    )
    with pytest.raises(error, match=reason):
        await service.record_funnel(
            command.client_id, uuid4(), "opened", principal=principal
        )
    assert facts.calls == ["client"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "funnel_id, stage",
    [(UUID(int=0), "opened"), ("untyped", "opened"), (uuid4(), "created")],
)
async def test_funnel_cannot_invent_server_stage_or_missing_identity(
    funnel_id, stage
):
    service, facts, command, principal = setup("telegram")
    with pytest.raises(ValueError, match="invalid_intake_funnel_stage"):
        await service.record_funnel(
            command.client_id, funnel_id, stage, principal=principal
        )
    assert facts.calls == []
