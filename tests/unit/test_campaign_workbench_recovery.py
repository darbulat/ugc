"""Recover accepted immutable draft receipts after current authority changes."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from tests.unit.test_campaign_draft_service import (
    CREATOR,
    OWNER,
    make_service,
    save_command,
)
from ugc_bot.miniapp.campaign_review_api import create_campaign_review_router


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["grant", "policy"])
async def test_original_receipt_remains_readable_after_revocation(changed):
    service = make_service()
    original = await service.save_draft(save_command(), session=object())
    if changed == "grant":
        service.foundation.grant["active"] = False
    else:
        service.foundation.policy["enabled"] = False
    with pytest.raises(PermissionError):
        await service.save_draft(save_command(), session=object())
    status = await service.operation_status(
        OWNER, "draft-create", session=object()
    )
    assert status["recorded"] is True
    assert status["original_result"] == original
    assert status["current"]["campaign_id"] == original["campaign_id"]
    assert status["is_current"] is True
    assert len(service.repository.rows) == 1
    assert len(service.repository.commands) == 1


@pytest.mark.asyncio
async def test_status_distinguishes_original_receipt_and_later_saved_revision():
    from uuid import UUID

    service = make_service()
    first = await service.save_draft(save_command(), session=object())
    await service.save_draft(
        save_command(
            key="new-version", campaign_id=UUID(first["campaign_id"]), version=1
        ),
        session=object(),
    )
    status = await service.operation_status(
        OWNER, "draft-create", session=object()
    )
    assert status["original_result"]["version"] == 1
    assert status["current"]["version"] == 2
    assert status["is_current"] is False
    absent = await service.operation_status(
        CREATOR, "draft-create", session=object()
    )
    assert absent == {
        "operation_key": "draft-create",
        "recorded": False,
        "as_of": "2026-10-24T00:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_signed_operation_status_read_is_scoped_private_and_no_store():
    service = make_service()
    saved = await service.save_draft(save_command(), session=object())

    @asynccontextmanager
    async def transaction():
        yield object()

    async def resolve(request, init_data, *, platform):
        return OWNER

    app = FastAPI()
    app.include_router(create_campaign_review_router(resolve))
    app.state.dispatcher = {
        "campaign_review_service": service,
        "transaction_manager": SimpleNamespace(transaction=transaction),
    }
    signed = {"init_data": "synthetic-native-proof", "platform": "max"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/campaigns/owned/operations/status",
            json={**signed, "operation_key": "draft-create"},
        )
        assert result.status_code == 200
        assert result.json()["original_result"] == saved
        assert result.headers["cache-control"] == "no-store"
        for extra in ({"actor_id": str(CREATOR)}, {"owner_id": str(CREATOR)}):
            bad = await client.post(
                "/campaigns/owned/operations/status",
                json={**signed, "operation_key": "draft-create", **extra},
            )
            assert bad.status_code == 422
            assert bad.json() == {"detail": "campaign_request_invalid"}
            assert bad.headers["cache-control"] == "no-store"
