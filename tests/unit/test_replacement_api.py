"""Native actor authority and strict bodies at the replacement boundary."""

from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from tests.application.services.test_replacement_service import (
    ADMIN_PROOF,
    CLIENT_PROOF,
    INTEREST,
    ITEM,
    setup,
)
from ugc_bot.miniapp.replacement_api import create_replacement_router


class Transactions:
    @asynccontextmanager
    async def transaction(self):
        yield object()


@pytest.mark.asyncio
async def test_request_decision_actor_comes_from_current_native_proof():
    repo, _, service = setup()
    principal = CLIENT_PROOF

    async def resolve(request, init_data, *, platform):
        return principal

    app = FastAPI()
    app.include_router(create_replacement_router(resolve))
    app.state.dispatcher = dict(
        replacement_service=service, transaction_manager=Transactions()
    )
    signed = dict(init_data="PRIVATE SIGNED DATA", platform="telegram")
    request = dict(
        **signed,
        operation_key="request",
        paid_item_id=str(ITEM),
        expected_assignment_version=1,
        candidate_interest_id=str(INTEREST),
        reason_code="refusal",
        reason="Отказ автора",
        evidence_reference="support:1",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        forged = await client.post(
            "/financial/replacements/request",
            json={**request, "actor_id": str(ADMIN_PROOF.user_id)},
        )
        assert (
            forged.status_code == 422
            and "PRIVATE SIGNED DATA" not in forged.text
        )
        assert forged.headers["cache-control"] == "no-store"
        assert (
            await client.post(
                "/financial/replacements/view",
                json={**signed, "paid_item_id": str(ITEM)},
            )
        ).status_code == 200
        assert (
            await client.post("/financial/replacements/queue", json=signed)
        ).status_code == 403
        assert (
            await client.post(
                "/financial/replacements/view?actor_id=forged",
                json={**signed, "paid_item_id": str(ITEM)},
            )
        ).status_code == 422
        result = await client.post(
            "/financial/replacements/request", json=request
        )
        assert result.status_code == 200, result.text
        pending = result.json()
        decision = dict(
            **signed,
            operation_key="approve",
            request_id=pending["request_id"],
            expected_version=1,
            action="approve",
            reason="Проверено",
            evidence_reference="support:review",
        )
        assert (
            await client.post("/financial/replacements/decision", json=decision)
        ).status_code == 403
        principal = ADMIN_PROOF
        approved = await client.post(
            "/financial/replacements/decision", json=decision
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["billable_positions_added"] == 0
        assert (
            repo.decisions[next(iter(repo.decisions))]["actor_id"]
            == ADMIN_PROOF.user_id
        )
        assert (
            await client.post("/financial/replacements/queue", json=signed)
        ).status_code == 200
        principal = CLIENT_PROOF
        contact = await client.post(
            "/financial/replacements/contact",
            json={
                **signed,
                "operation_key": "contact",
                "replacement_id": approved.json()["replacement_id"],
                "reason": "Получить контакт",
                "evidence_reference": "miniapp:explicit",
            },
        )
        assert contact.status_code == 200, contact.text
        principal = ADMIN_PROOF
        repo.actor[ADMIN_PROOF.user_id].is_admin = False
        assert (
            await client.post("/financial/replacements/decision", json=decision)
        ).status_code == 403
        app.state.dispatcher = {}
        assert (
            await client.post("/financial/replacements/queue", json=signed)
        ).status_code == 503
        principal = None
        assert (
            await client.post("/financial/replacements/queue", json=signed)
        ).status_code == 401
