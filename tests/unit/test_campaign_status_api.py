"""HTTP status reflects installed runtime and current publisher authority."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from tests.unit.test_campaign_draft_service import OWNER, make_service
from ugc_bot.application.campaign_moderation_ports import CampaignCapabilities
from ugc_bot.application.services.campaign_audience_service import (
    CampaignAudienceService,
)
from ugc_bot.miniapp.campaign_api import create_campaign_router
from ugc_bot.miniapp.campaign_review_api import create_campaign_review_router


@asynccontextmanager
async def transaction():
    yield object()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag,installed,ready,expected",
    [
        (True, True, True, "enabled"),
        (False, True, True, "paused"),
        (True, False, True, "unavailable"),
        (True, True, False, "unavailable"),
        (None, True, True, "unavailable"),
    ],
)
async def test_settings_delivery_status_requires_configured_installed_runtime(
    flag, installed, ready, expected
):
    async def resolve(*args, **kwargs):
        return OWNER

    async def view(*args, **kwargs):
        return {"publisher": {"active": True}, "policy": {"enabled": True}}

    async def capabilities(*args, **kwargs):
        return CampaignCapabilities(ready, ready, ready)

    methods = SimpleNamespace(
        submit=view,
        decide=view,
        view=view,
        respond=view,
        report=view,
        repository=SimpleNamespace(capabilities=capabilities),
    )
    app = FastAPI()
    app.state.config = SimpleNamespace(
        campaign=SimpleNamespace(delivery_enabled=flag)
    )
    app.state.dispatcher = {
        "campaign_service": SimpleNamespace(view=view),
        "campaign_submission_service": methods if installed else None,
        "campaign_moderation_service": methods if installed else None,
        "campaign_response_service": methods if installed else None,
        "transaction_manager": SimpleNamespace(transaction=transaction),
    }
    app.include_router(create_campaign_router(resolve))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/campaigns/settings", json={"init_data": "signed"}
        )
    assert result.status_code == 200
    assert result.json()["delivery_state"] == expected
    assert result.json()["capabilities"]["submit_campaign"] is (
        installed and ready
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("installed", [True, False])
async def test_draft_and_preview_report_actual_submission_availability(
    installed,
):
    async def resolve(*args, **kwargs):
        return OWNER

    async def submit(*args, **kwargs):
        raise AssertionError("A status read must not submit a campaign")

    async def capabilities(*args, **kwargs):
        return CampaignCapabilities(True, True, True)

    service = make_service()
    app = FastAPI()
    app.state.dispatcher = {
        "campaign_review_service": service,
        "campaign_audience_service": CampaignAudienceService(
            service.repository, service.foundation
        ),
        "campaign_submission_service": SimpleNamespace(
            submit=submit, repository=SimpleNamespace(capabilities=capabilities)
        )
        if installed
        else None,
        "transaction_manager": SimpleNamespace(transaction=transaction),
    }
    app.include_router(create_campaign_review_router(resolve))
    signed = {"init_data": "signed"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        saved = (
            await client.post(
                "/campaigns/owned/draft",
                json={
                    **signed,
                    "operation_key": "save",
                    "expected_version": 0,
                    "policy_version": 1,
                    "terms_hash": "a" * 64,
                    "content": {"title": "Task", "text": "Brief"},
                    "segment": {},
                },
            )
        ).json()
        expected = "available" if installed else "unavailable"
        assert saved["submission_state"] == expected
        target = {**signed, "campaign_id": saved["campaign_id"]}
        detail = (
            await client.post("/campaigns/owned/detail", json=target)
        ).json()
        preview = (
            await client.post(
                "/campaigns/owned/preview",
                json={
                    **target,
                    "revision_digest": saved["revision_digest"],
                },
            )
        ).json()
        listed = (
            await client.post("/campaigns/owned/list", json=signed)
        ).json()
        assert (
            detail["submission_state"]
            == preview["submission_state"]
            == expected
        )
        assert listed["drafts"][0]["submission_state"] == expected
        service.foundation.grant["active"] = False
        detail = (
            await client.post("/campaigns/owned/detail", json=target)
        ).json()
        assert detail["submission_state"] == "unavailable"
