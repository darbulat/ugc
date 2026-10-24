"""A persisted dispute precedes a delayed real payment consumer."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from tests.postgres_financial.test_work_entitlement_runtime import (
    obligations,
    start_flow,
    wallet,
)
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.collaboration_models import (
    CollaborationEventModel,
)
from ugc_bot.infrastructure.db.models import OutboxEventModel

capture_env = _capture_env


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_late_client_worker_uses_case_before_work_event_delivery(
    request,
    monkeypatch,
):
    env = request.getfixturevalue("capture_env")
    flow = await start_flow(env, monkeypatch)
    try:
        await flow["command"]("start", env["client"], 1)
        await flow["command"](
            "claim", flow["creator"], 2, evidence="actual proof"
        )
        await flow["command"](
            "dispute", env["client"], 3, reason="wrong content"
        )
        with Session(env["pg"]) as db:
            source_id = db.scalar(
                select(OutboxEventModel.event_id).where(
                    OutboxEventModel.aggregate_id == str(env["order"]),
                    OutboxEventModel.event_type
                    == "financial.client_snapshot_requested",
                )
            )
            case = db.scalar(
                select(CollaborationEventModel).where(
                    CollaborationEventModel.assignment_id == flow["assignment"],
                    CollaborationEventModel.event_type
                    == "financial.collaboration.disputed",
                )
            )
            case_id, case_event_id = case.parameters["case_id"], case.event_id
        publisher, _ = flow["container"].build_outbox_deps()
        child = publisher.financial_delivery
        source = await child.outbox_repo.get_by_id(source_id)
        await child._process_one_event(source, None, 3)
        assert {r["kind"] for r in obligations(env)} == {"client_referral"}
        values = wallet(env, flow["partner"])
        assert values["pending_minor"] == values["blocked_minor"] == 5000
        assert values["available_minor"] == values["reserved_minor"] == 0
        table = Base.metadata.tables["financial_movements"]
        grounds = Base.metadata.tables["financial_obligations"]
        with Session(env["pg"]) as db:
            entries = (
                db.execute(
                    select(table)
                    .join(grounds, grounds.c.id == table.c.obligation_id)
                    .where(grounds.c.order_id == env["order"])
                )
                .mappings()
                .all()
            )
            blocked = [e for e in entries if e["bucket_to"] == "blocked"]
            assert len(entries) == 3 and len(blocked) == 1
            assert str(blocked[0]["case_id"]) == case_id
            assert blocked[0]["event_id"] == str(case_event_id)
            assert db.get(OutboxEventModel, source_id).status == "published"
        await child._process_one_event(source, None, 3)
        assert wallet(env, flow["partner"]) == values
    finally:
        await flow["container"].session_factory.kw["bind"].dispose()
