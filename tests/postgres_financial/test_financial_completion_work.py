"""Resolution authority survives delayed money and scheduler advance."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from tests.postgres_financial.test_financial_completion import (
    financial_pg_engine as financial_pg_engine,
)
from tests.postgres_financial.test_v1_capture import capture_env as capture_env
from tests.postgres_financial.test_work_entitlement_runtime import (
    process_work_events,
    start_flow,
    wallet,
)
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import UserModel

__all__ = ["capture_env", "financial_pg_engine"]


@pytest.mark.asyncio
@pytest.mark.parametrize("success", (True, False))
async def test_reviewed_work_releases_or_cancels_actual_blocked_commission(
    capture_env, monkeypatch, success
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    try:
        await process_work_events(env, flow)
        await flow["command"]("start", env["client"], 1)
        await flow["command"](
            "claim", flow["creator"], 2, evidence="actual-content"
        )
        await flow["command"](
            "dispute", env["client"], 3, reason="Actual brief objection"
        )
        await process_work_events(env, flow)
        assert wallet(env, flow["partner"])["blocked_minor"] == 10000
        admin = uuid4()
        with Session(env["pg"]) as db, db.begin():
            db.add(
                UserModel(
                    user_id=admin,
                    messenger_type=MessengerType.TELEGRAM,
                    username="real-review-admin",
                    status=UserStatus.ACTIVE,
                    admin=True,
                )
            )
        lifecycle = flow["container"].build_bot_services()[
            "collaboration_service"
        ]
        async with flow["container"].transaction_manager.transaction() as db:
            queue = await lifecycle.list_disputes(admin, session=db)
            assert str(flow["assignment"]) in {
                i["assignment_id"] for i in queue["items"]
            }
        resolved = await flow["command"](
            "resolve_success" if success else "resolve_failure",
            admin,
            4,
            reason="Reviewed brief and actual content",
            evidence="private:admin-review",
        )
        if success:
            flow["clock"].at = resolved.collaboration.available_at
            await flow["command"](
                "advance", None, 5, system_actor="collaboration_scheduler"
            )
        await process_work_events(env, flow)
        money = wallet(env, flow["partner"])
        assert money["blocked_minor"] == 0
        if success:
            assert money["available_minor"] == 5000
            assert money["hold_minor"] == 5000
            assert wallet(env, flow["manager"])["available_minor"] == 60000
        else:
            assert money["cancelled_minor"] == 5000
            assert money["hold_minor"] == 5000
            assert money["available_minor"] == 0
    finally:
        await flow["container"].dispose()
