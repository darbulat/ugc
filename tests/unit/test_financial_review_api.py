"""Late financial reviews require current native admins and exact targets."""

from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.financial_review_api import create_financial_review_router


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_late_review_commands_are_pinned_to_native_admin_and_exact_minor(
    platform,
):
    actor, case = uuid4(), uuid4()
    calls = []

    class Service:
        error = None

        async def context(self, actor_id, **kwargs):
            assert actor_id == actor
            return dict(
                cases=[], grounds=[], has_more=False, page=kwargs["page"]
            )

        async def view(self, actor_id, identity, **kwargs):
            assert actor_id == actor
            return (
                dict(case_id=str(identity), version=1, state="open")
                if identity == case
                else None
            )

        async def open(self, command, **kwargs):
            if self.error:
                raise self.error
            calls.append((command, kwargs))
            return dict(
                case_id=str(case),
                version=1,
                state="open",
                amount_minor=10000,
                buckets={"paid": 9007199254740993},
            )

        async def resolve(self, command, **kwargs):
            calls.append((command, kwargs))
            return dict(
                case_id=str(case), version=2, target_minor=command.target_minor
            )

    class Transactions:
        session = object()
        calls = 0
        fail_at = None

        @asynccontextmanager
        async def transaction(self):
            self.calls += 1
            yield None if self.calls == self.fail_at else self.session

    class Admins:
        error = None

        async def context(self, actor_id, **kwargs):
            if self.error:
                raise self.error
            assert (
                actor_id == actor and kwargs["principal"].platform == platform
            )

    service, admins, transactions = Service(), Admins(), Transactions()

    async def resolver(request, init_data, *, platform):
        if init_data == "bare":
            return actor
        return (
            AuthenticatedMessengerPrincipal(actor, platform, "123")
            if init_data == "signed"
            else None
        )

    app = FastAPI()
    app.state.config = NS(financial=NS(core_enabled=True))
    app.state.dispatcher = dict(
        financial_review_service=service,
        partner_admin_service=admins,
        transaction_manager=transactions,
    )
    app.include_router(create_financial_review_router(resolver))
    base = dict(init_data="signed", platform=platform)
    opened = dict(
        base,
        operation_key="review-fact",
        business_key="actual-ground",
        expected_source_hash="a" * 64,
        reason="PRIVATE verified late claim",
        evidence_reference="PRIVATE actual proof",
        evidence_hash="b" * 64,
    )
    resolved = {k: v for k, v in opened.items() if k != "business_key"} | dict(
        case_id=str(case),
        expected_version=1,
        decision="cumulative_cancel",
        target_minor="9007199254740993",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def post(path, values=base):
            return await client.post(
                "/financial/reviews/admin" + path, json=values
            )

        response = await post("/context")
        assert (
            response.status_code == 200
            and response.headers["cache-control"] == "no-store"
        )
        assert response.json()["actor_id"] == str(actor)
        assert (await post("/open", opened)).json()["amount_minor"] == "10000"
        assert (await post("/open", opened)).json()["buckets"][
            "paid"
        ] == "9007199254740993"
        command, kwargs = calls[-1]
        assert (
            command.actor_id == actor
            and command.business_key == "actual-ground"
        )
        assert (
            kwargs["principal"].platform == platform
            and kwargs["session"] is transactions.session
        )
        response = await post("/resolve", resolved)
        assert (
            response.status_code == 200
            and response.json()["target_minor"] == "9007199254740993"
        )
        assert calls[-1][0].expected_source_hash == "a" * 64
        assert calls[-1][0].target_minor == 9007199254740993
        assert (
            await post(
                "/resolve",
                dict(resolved, decision="no_adjustment", target_minor=None),
            )
        ).status_code == 200
        assert (await post(f"/{case}/view")).status_code == 200
        assert (await post(f"/{uuid4()}/view")).status_code == 404
        for target in (True, 100, "-1", "1e3", "00"):
            assert (
                await post("/resolve", dict(resolved, target_minor=target))
            ).status_code == 422
        for values in (
            dict(opened, actor_id=str(actor)),
            dict(opened, source={}),
            dict(opened, expected_source_hash="forged"),
        ):
            assert (await post("/open", values)).status_code == 422
        assert (await post("/context?actor=forged")).status_code == 422
        for token in ("bare", "invalid"):
            assert (
                await post("/context", dict(base, init_data=token))
            ).status_code == 401
        for error, status in (
            (ValueError("idempotency_payload_conflict"), 409),
            (ValueError("PRIVATE"), 503),
            (RuntimeError("PRIVATE"), 503),
        ):
            service.error = error
            response = await post("/open", opened)
            assert (
                response.status_code == status
                and "PRIVATE" not in response.text
            )
        service.error = None
        admins.error = ValueError("active_admin_required")
        before = len(calls)
        assert (await post("/open", opened)).status_code == 403
        assert len(calls) == before
        admins.error = None
        app.state.config.financial.core_enabled = False
        assert (await post("/context")).json()["writes_paused"]
        assert (await post("/open", opened)).status_code == 503
        assert (await post("/resolve", resolved)).status_code == 503
        app.state.config.financial.core_enabled = True
        transactions.fail_at = transactions.calls + 2
        assert (await post("/context")).status_code == 503
        transactions.fail_at = None
        transactions.session = None
        assert (await post("/context")).status_code == 503
        transactions.session = object()
        del app.state.dispatcher["partner_admin_service"]
        assert (await post("/context")).status_code == 503
        app.state.dispatcher = {}
        assert (await post("/context")).status_code == 503
