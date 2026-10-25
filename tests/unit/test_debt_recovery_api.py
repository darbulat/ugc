"""Signed repayments redact failures and enforce exact wire amounts."""

from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.debt_recovery_api import create_debt_recovery_router
from ugc_bot.miniapp.selection_maturity_api import (
    create_selection_maturity_router,
)


class Transactions:
    @asynccontextmanager
    async def transaction(self):
        yield object()


@pytest.mark.asyncio
async def test_signed_repayment_exact_amounts_authority_and_safe_failures():
    actor = uuid4()
    calls = []

    class Service:
        error = None

        async def context(self, actor_id, **kwargs):
            if self.error:
                raise self.error
            return dict(
                actor_id=str(actor_id),
                cases=[],
                observations=[],
                page=kwargs["page"],
                has_more=False,
            )

        async def observe(self, command, **kwargs):
            if self.error:
                raise self.error
            calls.append(command)
            return dict(
                observation_id=str(uuid4()), amount_minor=command.amount_minor
            )

        async def apply(self, command, **kwargs):
            if self.error:
                raise self.error
            calls.append(command)
            return dict(applied=True, recovered_minor=20000)

    service = Service()

    async def resolve(request, init_data, *, platform):
        return (
            AuthenticatedMessengerPrincipal(actor, platform, "123")
            if init_data == "signed"
            else None
        )

    app = FastAPI()
    app.include_router(create_debt_recovery_router(resolve))
    app.state.config = NS(financial=NS(core_enabled=True))
    app.state.dispatcher = dict(
        debt_recovery_service=service, transaction_manager=Transactions()
    )
    body = dict(
        init_data="signed",
        operation_key="review",
        case_id=str(uuid4()),
        reason="PRIVATE reason",
        evidence_reference="PRIVATE proof",
        evidence_hash="a" * 64,
        recipient_id=str(uuid4()),
        amount_minor="20000",
        currency="RUB",
        bank_account_label="test",
        bank_reference="actual-test-reference",
        occurred_at="2026-10-25T00:00:00Z",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def post(path, values):
            return await client.post(
                "/financial/debts/admin" + path, json=values
            )

        response = await post("/context", dict(init_data="signed"))
        assert (
            response.status_code == 200
            and response.headers["cache-control"] == "no-store"
        )
        response = await post("/observe", body)
        assert (
            response.status_code == 200
            and response.json()["amount_minor"] == "20000"
        )
        assert calls[-1].actor_id == actor and calls[-1].amount_minor == 20000
        for invalid in (True, 20000, 1.5, "2e4", None):
            response = await post("/observe", dict(body, amount_minor=invalid))
            assert response.status_code in (409, 422)
            assert "PRIVATE" not in response.text
        assert (
            await post("/observe", dict(body, actor_id=str(actor)))
        ).status_code == 422
        assert (
            await post("/context?actor=forged", dict(init_data="signed"))
        ).status_code == 422
        assert (
            await post("/context", dict(init_data="invalid"))
        ).status_code == 401
        for error, status in (
            (PermissionError("PRIVATE"), 403),
            (ValueError("financial_principal_changed"), 403),
            (ValueError("PRIVATE"), 409),
            (RuntimeError("PRIVATE"), 503),
        ):
            service.error = error
            response = await post("/context", dict(init_data="signed"))
            assert (
                response.status_code == status
                and "PRIVATE" not in response.text
            )
        service.error = None
        application = {
            k: body[k]
            for k in (
                "init_data",
                "operation_key",
                "case_id",
                "reason",
                "evidence_reference",
                "evidence_hash",
            )
        }
        application.update(
            observation_id=str(uuid4()),
            business_key="actual-ground",
            expected_debt_minor="30000",
        )
        assert (await post("/apply", application)).status_code == 200
        app.state.config.financial.core_enabled = False
        assert (await post("/apply", application)).status_code == 503
        assert (await post("/observe", body)).status_code == 200
        app.state.dispatcher = {}
        assert (
            await post("/context", dict(init_data="signed"))
        ).status_code == 503


@pytest.mark.asyncio
async def test_selection_close_uses_current_actor_and_dependencies():
    actor, order = uuid4(), uuid4()

    class Maturity:
        async def refresh(self, order_id, **kwargs):
            assert order_id == order and kwargs["actor_id"] == actor
            return dict(state="closed")

    async def resolve(request, init_data, *, platform):
        return (
            AuthenticatedMessengerPrincipal(actor, platform, "123")
            if init_data == "signed"
            else None
        )

    app = FastAPI()
    app.include_router(create_selection_maturity_router(resolve))
    app.state.config = NS(financial=NS(core_enabled=True))
    app.state.dispatcher = dict(
        selection_maturity_service=Maturity(),
        transaction_manager=Transactions(),
    )
    body = dict(
        init_data="signed", reason="Reviewed closure", evidence="Evidence"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        path = f"/financial/orders/{order}/selection/close"
        assert (await client.post(path, json=body)).json() == dict(
            state="closed"
        )
        assert (
            await client.post(path + "?forged=1", json=body)
        ).status_code == 422
        assert (
            await client.post(path, json=dict(body, init_data="invalid"))
        ).status_code == 401
        app.state.config.financial.core_enabled = False
        assert (await client.post(path, json=body)).status_code == 503
        app.state.config.financial.core_enabled = True
        app.state.dispatcher = {}
        assert (await client.post(path, json=body)).status_code == 503
