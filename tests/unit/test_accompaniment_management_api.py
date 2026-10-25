"""An explicit signed decision reaches only the reviewed management contract."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ugc_bot.application.accompaniment_refund_ports import (
    ReviewAccompanimentManagement,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.accompaniment_refund_api import (
    create_accompaniment_refund_router,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["continue", "cancel", "forged"])
async def test_management_route_uses_typed_review_and_current_principal(
    decision,
):
    principal = AuthenticatedMessengerPrincipal(uuid4(), "telegram", "123")
    resolver = AsyncMock(return_value=principal)
    service = SimpleNamespace(
        review_management=AsyncMock(return_value={"work_version": 4})
    )

    @asynccontextmanager
    async def transaction():
        yield "caller-session"

    app = FastAPI()
    app.state.config = SimpleNamespace(
        financial=SimpleNamespace(core_enabled=True)
    )
    app.state.dispatcher = {
        "accompaniment_refund_service": service,
        "transaction_manager": SimpleNamespace(transaction=transaction),
    }
    app.include_router(create_accompaniment_refund_router(resolver))
    payload = {
        "init_data": "signed",
        "platform": "telegram",
        "operation_key": "review",
        "paid_item_id": str(uuid4()),
        "application_id": str(uuid4()),
        "expected_work_version": 3,
        "decision": decision,
        "reason": "Reviewed remaining service",
        "evidence_reference": "proof",
        "evidence_hash": "a" * 64,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/financial/corrections/admin/accompaniment/management",
            json=payload,
        )
    assert response.headers["cache-control"] == "no-store"
    assert response.status_code == (422 if decision == "forged" else 200), (
        response.text
    )
    if decision == "forged":
        service.review_management.assert_not_awaited()
    else:
        args = service.review_management.await_args
        assert isinstance(args.args[0], ReviewAccompanimentManagement)
        assert (
            args.args[0].decision == decision
            and args.args[0].actor_id == principal.user_id
        )
        assert args.kwargs == {
            "session": "caller-session",
            "principal": principal,
        }


@pytest.mark.asyncio
async def test_absent_work_apply_accepts_only_zero_version_not_management():
    principal = AuthenticatedMessengerPrincipal(uuid4(), "telegram", "123")
    resolver = AsyncMock(return_value=principal)
    service = SimpleNamespace(apply=AsyncMock(return_value={"applied": True}))

    @asynccontextmanager
    async def transaction():
        yield "caller-session"

    app = FastAPI()
    app.state.config = SimpleNamespace(
        financial=SimpleNamespace(core_enabled=True)
    )
    app.state.dispatcher = dict(
        accompaniment_refund_service=service,
        transaction_manager=SimpleNamespace(transaction=transaction),
    )
    app.include_router(create_accompaniment_refund_router(resolver))
    base = dict(
        init_data="signed",
        operation_key="review-absence",
        paid_item_id=str(uuid4()),
        expected_work_version=0,
        reason="Reviewed absence of initialized work",
        evidence_reference="proof",
        evidence_hash="a" * 64,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/financial/corrections/admin/accompaniment/apply",
            json=dict(
                base,
                observation_id=str(uuid4()),
                reviewed_customer_target_minor="2000",
                reviewed_manager_target_minor="0",
            ),
        )
        assert response.status_code == 200
        assert service.apply.await_args.args[0].expected_work_version == 0
        response = await client.post(
            "/financial/corrections/admin/accompaniment/management",
            json=dict(
                base,
                application_id=str(uuid4()),
                decision="continue",
            ),
        )
        assert response.status_code == 422
