"""Real held grants progress past a temporarily ineligible early recipient."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.helpers.factories import create_test_user
from tests.postgres_financial.test_financial_completion import (
    completion as _completion,
)
from tests.postgres_financial.test_order_intake import intake_env as _intake_env
from ugc_bot.application.manual_grant_ports import ApproveManualGrant
from ugc_bot.container.manual_grant_factory import build_manual_grants
from ugc_bot.infrastructure.db.models import UserModel

intake_env = _intake_env
completion = _completion


@pytest.mark.asyncio
async def test_real_grant_cursor_does_not_starve_later_available_recipient(
    completion,
):
    rt, _ = completion
    env = rt.env
    config = env["config"]
    config.financial.superadmin_user_ids_raw = str(env["admin"].user_id)
    tm = env["container"].transaction_manager
    service, sweep = build_manual_grants(config, tm)
    service.clock = env["clock"]
    members = [
        await create_test_user(
            env["repos"]["user_repo"], external_id=str(uuid4().int % 10**12 + 1)
        )
        for _ in range(2)
    ]
    command = ApproveManualGrant(
        actor_id=env["admin"].user_id,
        operation_key="cursor:" + uuid4().hex,
        paid_item_id=rt.facts["order"].items[0].paid_item_id,
        recipient_id=members[0].user_id,
        amount_minor=12345,
        currency="RUB",
        reason="Synthetic cursor fixture",
        evidence_reference="synthetic:review",
        evidence_hash="a" * 64,
    )
    grants = []
    for member in members:
        async with tm.transaction() as db:
            receipt = await service.approve(
                replace(
                    command,
                    operation_key="cursor:" + uuid4().hex,
                    recipient_id=member.user_id,
                ),
                session=db,
            )
        grants.append((UUID(receipt["grant_id"]), member.user_id))
    grants.sort()
    env["clock"].at += timedelta(days=14)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == grants[0][1])
            .values(status="new")
        )
    assert (await sweep.run_once(limit=1))["deferred"] == 1
    assert (await sweep.run_once(limit=1))["matured"] == 1
    assert (await sweep.run_once(limit=1))["attempted"] == 0
    async with tm.transaction() as db:
        first = await service.ledger.repository.read_projection(
            grants[0][1], "RUB", session=db
        )
        second = await service.ledger.repository.read_projection(
            grants[1][1], "RUB", session=db
        )
    assert first["hold"] == 12345 and first["available"] == 0
    assert second["available"] == 12345 and second["hold"] == 0
