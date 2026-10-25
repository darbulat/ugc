"""Positive adjustments use strict native authority and exact minor amounts."""

from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.manual_grant_api import create_manual_grant_router


class Transactions:
    session = object()
    calls = 0
    fail_at = None

    @asynccontextmanager
    async def transaction(self):
        self.calls += 1
        yield None if self.calls == self.fail_at else self.session


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_grant_native_authority_exact_amounts_and_private_errors(
    platform,
):
    actor, item, recipient, grant = [uuid4() for _ in range(4)]
    calls = []

    class Service:
        superadmins = {actor}
        error = None

        async def approve(self, command, **kwargs):
            if self.error:
                raise self.error
            calls.append((command, kwargs))
            return dict(grant_id=grant, amount_minor=command.amount_minor)

        async def mature(self, identity, **kwargs):
            calls.append((identity, kwargs))
            return dict(grant_id=identity, mature=False)

    class Admins:
        error = None

        async def context(self, actor_id, **kwargs):
            assert (
                actor_id == actor and kwargs["principal"].platform == platform
            )
            if self.error:
                raise self.error
            return dict(capabilities={})

    service, admins, transactions = Service(), Admins(), Transactions()

    async def resolve(request, init_data, *, platform):
        if init_data == "wrong-platform":
            return AuthenticatedMessengerPrincipal(actor, "max", "456")
        if init_data == "bare-id":
            return actor
        if init_data != "signed":
            return None
        return AuthenticatedMessengerPrincipal(actor, platform, "123")

    app = FastAPI()
    app.include_router(create_manual_grant_router(resolve))
    app.state.config = NS(financial=NS(core_enabled=True))
    app.state.dispatcher = dict(
        manual_grant_service=service,
        partner_admin_service=admins,
        transaction_manager=transactions,
    )
    base = dict(init_data="signed", platform=platform)
    body = dict(
        **base,
        operation_key="actual-reviewed-grant",
        paid_item_id=str(item),
        recipient_id=str(recipient),
        amount_minor="9007199254740993",
        currency="RUB",
        reason="PRIVATE actual reason",
        evidence_reference="PRIVATE reference",
        evidence_hash="a" * 64,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def post(path, values=base):
            return await client.post(
                "/financial/grants/admin" + path, json=values
            )

        response = await post("/context")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == dict(
            actor_id=str(actor),
            can_approve=True,
            can_mature=True,
            writes_paused=False,
        )
        response = await post("/approve", body)
        assert response.status_code == 200
        assert response.json()["amount_minor"] == "9007199254740993"
        command, kwargs = calls[-1]
        assert (
            command.actor_id == actor
            and command.amount_minor == 9007199254740993
        )
        assert kwargs["session"] is transactions.session
        assert kwargs["principal"].platform == platform
        response = await post("/mature", dict(**base, grant_id=str(grant)))
        assert response.status_code == 200 and not response.json()["mature"]
        assert calls[-1][0] == grant and calls[-1][1]["actor_id"] == actor
        for invalid in (True, 100, 1.5, "1e3", "00", "0", "-1", None):
            response = await post("/approve", dict(body, amount_minor=invalid))
            assert (
                response.status_code == 422 and "PRIVATE" not in response.text
            )
        for values in (
            dict(body, actor_id=str(actor)),
            dict(body, currency="USD"),
        ):
            assert (await post("/approve", values)).status_code == 422
        assert (await post("/context?actor=forged")).status_code == 422
        for token in ("invalid", "bare-id"):
            assert (
                await post("/context", dict(base, init_data=token))
            ).status_code == 401
        if platform == "telegram":
            assert (
                await post("/context", dict(base, init_data="wrong-platform"))
            ).status_code == 401
        for error, status in (
            (PermissionError("financial_superadmin_required"), 403),
            (ValueError("idempotency_payload_conflict"), 409),
            (ValueError("PRIVATE reason"), 503),
            (RuntimeError("PRIVATE proof"), 503),
        ):
            service.error = error
            response = await post("/approve", body)
            assert (
                response.status_code == status
                and "PRIVATE" not in response.text
            )
        service.error = None
        service.superadmins = set()
        assert not (await post("/context")).json()["can_approve"]
        before = len(calls)
        assert (await post("/approve", body)).status_code == 403
        assert len(calls) == before
        admins.error = PermissionError("active_admin_required")
        assert (await post("/context")).status_code == 403
        admins.error = None
        app.state.config.financial.core_enabled = False
        assert (await post("/context")).json()["writes_paused"]
        assert (await post("/approve", body)).status_code == 503
        assert (
            await post("/mature", dict(**base, grant_id=str(grant)))
        ).status_code == 503
        app.state.config.financial.core_enabled = True
        transactions.fail_at = transactions.calls + 2
        service.superadmins = {actor}
        assert (await post("/approve", body)).status_code == 503
        transactions.fail_at = None
        transactions.session = None
        assert (await post("/context")).status_code == 503
        transactions.session = object()
        del app.state.dispatcher["partner_admin_service"]
        assert (await post("/context")).status_code == 503
        app.state.dispatcher = {}
        assert (await post("/context")).status_code == 503


@pytest.mark.asyncio
async def test_manual_grant_scheduler_keeps_retrying_without_proof_leak(
    monkeypatch, caplog
):
    from ugc_bot.manual_grant_scheduler import run_loop

    calls, sleeps = [], []

    class Sweep:
        async def run_once(self):
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("PRIVATE proof")

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("ugc_bot.manual_grant_scheduler.asyncio.sleep", sleep)
    await run_loop(Sweep(), interval_seconds=1, max_iterations=2)
    assert len(calls) == 2 and sleeps == [1] and "PRIVATE" not in caplog.text
    for values in (dict(interval_seconds=0), dict(max_iterations=0)):
        with pytest.raises(ValueError, match="bounds_invalid"):
            await run_loop(Sweep(), **values)
