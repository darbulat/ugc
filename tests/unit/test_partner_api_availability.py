"""Current-account and availability failures disclose no partial data."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from tests.application.services.test_partner_view_service import (
    ACTOR,
    NOW,
    Repository,
    facts,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.partner_view_service import PartnerViewService
from ugc_bot.miniapp.partner_api import create_partner_router


class Transactions:
    @asynccontextmanager
    async def transaction(self):
        yield object()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,status",
    [
        ("service", 503),
        ("transactions", 503),
        ("blocked", 403),
        ("disappeared", 404),
        ("clock", 503),
    ],
)
async def test_partner_current_source_and_capability_failures(case, status):
    async def principal(request, init_data, *, platform):
        return AuthenticatedMessengerPrincipal(ACTOR, platform, "123")

    value = (
        None
        if case == "disappeared"
        else replace(
            facts(), account_status="blocked" if case == "blocked" else "active"
        )
    )
    clock = SimpleNamespace(
        now=lambda: datetime(2026, 10, 23) if case == "clock" else NOW
    )
    service = PartnerViewService(
        Repository(value), clock, {"telegram": "synthetic"}
    )
    app = FastAPI()
    app.include_router(create_partner_router(principal), prefix="/api")
    app.state.config = SimpleNamespace(
        financial=SimpleNamespace(core_enabled=False)
    )
    app.state.dispatcher = {
        "partner_view_service": None if case == "service" else service,
        "transaction_manager": None
        if case == "transactions"
        else Transactions(),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/partner/view", json={"init_data": "synthetic-signed-envelope"}
        )
        assert response.status_code == status
        assert (
            "network" not in response.json()
            and "financial" not in response.json()
        )
        assert "aware_timestamp" not in response.text


@pytest.mark.asyncio
async def test_partner_repository_refuses_non_snapshot_database():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ugc_bot.infrastructure.db.repositories.partner_view import (
        SqlAlchemyPartnerViewRepository,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with async_sessionmaker(engine).begin() as db:
            with pytest.raises(
                ValueError, match="partner_snapshot_postgres_required"
            ):
                await SqlAlchemyPartnerViewRepository().read(
                    ACTOR, NOW, network_page=0, assignment_page=0, session=db
                )
    finally:
        await engine.dispose()
