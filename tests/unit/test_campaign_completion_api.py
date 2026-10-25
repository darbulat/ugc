"""Signed APIs retain the caller transaction and return safe errors."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.campaign_analytics_api import (
    create_campaign_analytics_router,
)
from ugc_bot.miniapp.campaign_runtime_api import create_campaign_runtime_router

AT = datetime(2026, 10, 25, tzinfo=timezone.utc)
ID = str(uuid4())


class Transactions:
    @asynccontextmanager
    async def transaction(self):
        yield "caller-session"


def application():
    app = FastAPI()
    principal = AuthenticatedMessengerPrincipal(uuid4(), "telegram", "123")
    resolver = AsyncMock(return_value=principal)
    analytics = SimpleNamespace(
        **{
            name: AsyncMock(return_value={"confirmed": True})
            for name in (
                "publish",
                "import_events",
                "close_source",
                "record_paid_pilot",
                "report",
            )
        }
    )
    response = SimpleNamespace(
        **{
            name: AsyncMock(return_value={"confirmed": True})
            for name in ("view", "respond", "report")
        }
    )
    app.state.dispatcher = {
        "campaign_analytics_service": analytics,
        "campaign_response_service": response,
        "transaction_manager": Transactions(),
    }
    app.include_router(create_campaign_analytics_router(resolver))
    app.include_router(create_campaign_runtime_router(resolver))
    return app, resolver, analytics, response


SOURCE = {
    "subject_type": "campaign",
    "subject_id": ID,
    "source_name": "source",
    "account_label": "account",
    "attribution_from": (AT - timedelta(days=2)).isoformat(),
    "attribution_until": (AT - timedelta(days=1)).isoformat(),
    "marketing_spend_minor": 10000,
    "currency": "RUB",
    "metrics": ["views"],
    "proof_reference": "proof",
    "budget_reference": "spend",
    "reason": "Reviewed evidence",
}
CASES = [
    (
        "/analytics/admin/sources/publish",
        "publish",
        {"operation_key": "publish", **SOURCE},
    ),
    (
        "/analytics/admin/events/import",
        "import_events",
        {
            "operation_key": "import",
            "source_id": ID,
            "events": [
                {
                    "external_event_id": "event",
                    "kind": "view",
                    "occurred_at": AT.isoformat(),
                    "entity_id": "video",
                    "quantity": 1,
                }
            ],
        },
    ),
    (
        "/analytics/admin/sources/close",
        "close_source",
        {
            "operation_key": "close",
            "source_id": ID,
            "action": "finalize",
            "proof_reference": "proof",
            "reason": "reviewed",
        },
    ),
    (
        "/analytics/admin/paid-pilots/record",
        "record_paid_pilot",
        {
            "operation_key": "pilot",
            "subject_type": "campaign",
            "subject_id": ID,
            "payment_reference": "paid",
            "paid_minor": 10000,
            "currency": "RUB",
            "proof_reference": "proof",
        },
    ),
    (
        "/analytics/owned/report",
        "report",
        {"subject_type": "campaign", "subject_id": ID},
    ),
    ("/campaigns/recipient/view", "view", {"campaign_id": ID}),
    (
        "/campaigns/recipient/respond",
        "respond",
        {
            "campaign_id": ID,
            "operation_key": "response",
            "expected_version": 0,
            "choice": "interested",
        },
    ),
    ("/campaigns/owned/report", "report", {"campaign_id": ID}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("path,method,payload", CASES)
async def test_typed_routes_pass_native_principal_and_exact_caller_session(
    path, method, payload
):
    app, resolver, analytics, response = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            path,
            json={"init_data": "signed", "platform": "telegram", **payload},
        )
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    call = getattr(
        analytics if path.startswith("/analytics") else response, method
    ).await_args
    assert (
        call.args[0] == resolver.return_value.user_id
        and call.kwargs["session"] == "caller-session"
    )
    assert call.kwargs["principal"] is resolver.return_value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition,status",
    [
        ("query", 422),
        ("principal", 401),
        ("missing_service", 503),
        ("missing_transaction", 503),
        ("internal", 503),
        ("denied", 403),
        ("body", 422),
    ],
)
@pytest.mark.parametrize("analytics", [True, False])
async def test_read_rejects_overrides_dependencies_and_private_errors(
    condition, status, analytics
):
    app, resolver, a, r = application()
    path = (
        "/analytics/owned/report" if analytics else "/campaigns/recipient/view"
    )
    payload = (
        {"subject_type": "campaign", "subject_id": ID}
        if analytics
        else {"campaign_id": ID}
    )
    if condition == "query":
        path += "?actor_id=forged"
    if condition == "principal":
        resolver.return_value = None
    if condition == "missing_service":
        app.state.dispatcher.pop(
            "campaign_analytics_service"
            if analytics
            else "campaign_response_service"
        )
    if condition == "missing_transaction":
        app.state.dispatcher.pop("transaction_manager")
    if condition == "internal":
        (a.report if analytics else r.view).side_effect = RuntimeError(
            "PRIVATE SQL DETAILS"
        )
    if condition == "denied":
        (a.report if analytics else r.view).side_effect = PermissionError(
            "analytics_current_actor_required"
            if analytics
            else "campaign_owner_required"
        )
    if condition == "body":
        payload["owner_id"] = ID
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            path,
            json={"init_data": "signed", "platform": "telegram", **payload},
        )
    assert result.status_code == status, result.text
    assert (
        result.headers["cache-control"] == "no-store"
        and "PRIVATE" not in result.text
    )
