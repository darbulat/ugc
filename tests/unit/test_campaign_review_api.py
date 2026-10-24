"""The focused router exposes own drafts without targeting overrides."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from tests.unit.test_campaign_draft_service import OWNER, make_service


@asynccontextmanager
async def transaction():
    yield object()


@pytest.mark.asyncio
async def test_router_saves_for_resolved_actor_and_rejects_targeting_or_query():
    from ugc_bot.application.services.campaign_audience_service import (
        CampaignAudienceService,
    )
    from ugc_bot.miniapp.campaign_review_api import (
        create_campaign_review_router,
    )

    service = make_service()

    async def resolve(request, init_data, *, platform):
        return OWNER

    app = FastAPI()
    app.include_router(create_campaign_review_router(resolve))
    app.state.dispatcher = {
        "campaign_review_service": service,
        "campaign_audience_service": CampaignAudienceService(
            service.repository, service.foundation
        ),
        "transaction_manager": SimpleNamespace(transaction=transaction),
    }
    signed = {
        "init_data": "synthetic already validated principal",
        "platform": "max",
    }
    body = {
        **signed,
        "operation_key": "save",
        "expected_version": 0,
        "policy_version": 1,
        "terms_hash": "a" * 64,
        "content": {"title": "Task", "text": "Exact"},
        "segment": {},
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post("/campaigns/owned/draft", json=body)
        assert result.status_code == 200
        saved = result.json()
        preview = await client.post(
            "/campaigns/owned/preview",
            json={
                **signed,
                "campaign_id": saved["campaign_id"],
                "revision_digest": saved["revision_digest"],
            },
        )
        assert (
            preview.status_code == 200 and preview.json()["eligible_count"] == 0
        )
        assert (await client.post("/campaigns/owned/list", json=signed)).json()[
            "drafts"
        ][0]["campaign_id"] == saved["campaign_id"]
        assert (
            await client.post(
                "/campaigns/owned/detail",
                json={**signed, "campaign_id": saved["campaign_id"]},
            )
        ).status_code == 200
        for extra in (
            {"owner_id": str(OWNER)},
            {"recipient_ids": []},
            {"is_admin": True},
        ):
            assert (
                await client.post(
                    "/campaigns/owned/draft", json={**body, **extra}
                )
            ).status_code == 422
        assert (
            await client.post(
                "/campaigns/owned/detail?owner_id=foreign",
                json={**signed, "campaign_id": saved["campaign_id"]},
            )
        ).status_code == 422
        assert (
            await client.post("/campaigns/admin/approve", json=signed)
        ).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform,token", [("telegram", "tg-synthetic"), ("max", "max-synthetic")]
)
async def test_real_signed_principal_protects_draft_routes(platform, token):
    from time import time

    from tests.unit.test_miniapp_session_freshness import signed
    from ugc_bot.miniapp.api import _ensure_recent_user_and_get_id
    from ugc_bot.miniapp.campaign_review_api import (
        create_campaign_review_router,
    )

    class Roles:
        async def get_user(self, **kwargs):
            return SimpleNamespace(user_id=OWNER, country="ru")

    app = FastAPI()
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="tg-synthetic"),
        max_bot=SimpleNamespace(token="max-synthetic"),
    )
    app.state.dispatcher = {
        "campaign_review_service": make_service(),
        "transaction_manager": SimpleNamespace(transaction=transaction),
        "user_role_service": Roles(),
    }
    app.include_router(
        create_campaign_review_router(_ensure_recent_user_and_get_id)
    )
    current = signed(str(int(time())), bot_token=token)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post(
                "/campaigns/owned/list",
                json={"platform": platform, "init_data": current},
            )
        ).status_code == 200
        invalid = [
            signed(str(int(time()) - 90000), bot_token=token),
            current + "&auth_date=1",
            current + "&user=%7B%7D",
            signed(str(int(time())), bot_token="wrong-synthetic"),
        ]
        for raw in invalid:
            assert (
                await client.post(
                    "/campaigns/owned/list",
                    json={"platform": platform, "init_data": raw},
                )
            ).status_code == 401


@pytest.mark.asyncio
async def test_actual_route_errors_keep_conflict_not_found_and_setup_distinct():
    from ugc_bot.miniapp.campaign_review_api import (
        create_campaign_review_router,
    )

    async def resolve(*args, **kwargs):
        return OWNER

    app = FastAPI()
    app.include_router(create_campaign_review_router(resolve))
    app.state.dispatcher = {
        "transaction_manager": SimpleNamespace(transaction=transaction)
    }
    envelope = {"init_data": "synthetic validated", "platform": "telegram"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post("/campaigns/owned/list", json=envelope)
        ).status_code == 503
        service = make_service()
        app.state.dispatcher["campaign_review_service"] = service
        assert (
            await client.post(
                "/campaigns/owned/detail",
                json={**envelope, "campaign_id": str(OWNER)},
            )
        ).status_code == 404
        payload = {
            **envelope,
            "operation_key": "save",
            "expected_version": 0,
            "policy_version": 2,
            "terms_hash": "a" * 64,
            "content": {"title": "Task", "text": "Brief"},
            "segment": {},
        }
        assert (
            await client.post("/campaigns/owned/draft", json=payload)
        ).status_code == 409
        payload["policy_version"] = 1
        payload["content"]["link"] = "http://unsafe.example"
        assert (
            await client.post("/campaigns/owned/draft", json=payload)
        ).status_code == 422
        del payload["content"]["link"]
        service.foundation.grant["active"] = False
        assert (
            await client.post("/campaigns/owned/draft", json=payload)
        ).status_code == 403


@pytest.mark.asyncio
async def test_validation_privacy_and_every_response_is_no_store(
    caplog,
):
    from ugc_bot.miniapp.campaign_review_api import (
        create_campaign_review_router,
    )

    async def resolve(*args, **kwargs):
        return OWNER

    app = FastAPI()
    app.include_router(create_campaign_review_router(resolve))
    app.state.dispatcher = {
        "campaign_review_service": make_service(),
        "transaction_manager": SimpleNamespace(transaction=transaction),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/campaigns/owned/list",
            json={"init_data": "PRIVATE_AUTH_781", "page": "PRIVATE_DRAFT_782"},
        )
        assert response.status_code == 422
        assert response.json() == {"detail": "campaign_request_invalid"}
        assert response.headers["Cache-Control"] == "no-store"
        assert "PRIVATE_" not in response.text and "PRIVATE_" not in caplog.text
        success = await client.post(
            "/campaigns/owned/list", json={"init_data": "validated"}
        )
        assert (
            success.status_code == 200
            and success.headers["Cache-Control"] == "no-store"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status,code",
    [
        (ValueError("campaign_invalid_page"), 422, "campaign_invalid_page"),
        (ValueError("PRIVATE_SOURCE_123"), 503, "campaign_drafts_unavailable"),
        (
            PermissionError("PRIVATE_SOURCE_123"),
            503,
            "campaign_drafts_unavailable",
        ),
        (LookupError("PRIVATE_SOURCE_123"), 503, "campaign_drafts_unavailable"),
        (
            RuntimeError("PRIVATE_SOURCE_123"),
            503,
            "campaign_drafts_unavailable",
        ),
    ],
)
async def test_unknown_service_errors_never_echo_or_log_private_content(
    error, status, code, caplog
):
    from ugc_bot.miniapp.campaign_review_api import (
        create_campaign_review_router,
    )

    async def resolve(*args, **kwargs):
        return OWNER

    async def broken(*args, **kwargs):
        raise error

    app = FastAPI()
    app.include_router(create_campaign_review_router(resolve))
    app.state.dispatcher = {
        "campaign_review_service": SimpleNamespace(list_drafts=broken),
        "transaction_manager": SimpleNamespace(transaction=transaction),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/campaigns/owned/list", json={"init_data": "PRIVATE_AUTH_124"}
        )
        assert response.status_code == status and response.json() == {
            "detail": code
        }
        assert response.headers["Cache-Control"] == "no-store"
        assert "PRIVATE_" not in response.text and "PRIVATE_" not in caplog.text
