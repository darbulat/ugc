"""An actual post-payment grade increase cannot reprice the paid position."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_creator_social import seed_profile
from tests.postgres_financial.test_identity_history_postgres import (
    count_at,
    direct_binding,
    instant,
)
from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from tests.postgres_financial.test_work_entitlement_runtime import (
    finish_work,
    obligations,
    process_work_events,
    start_flow,
    wallet,
)
from ugc_bot.infrastructure.db.base import Base

capture_env = _capture_env


def add_verified_creators(env, partner, count):
    with env["pg"].begin() as connection:
        for _ in range(count):
            creator = seed_profile(connection, stable_id=str(uuid4()))
            direct_binding(connection, partner, creator)
        return instant(connection)


@pytest.mark.asyncio
async def test_grade_99_to_100_after_capture_does_not_reprice_work(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(
        env,
        monkeypatch,
        before_capture=lambda partner, creator: add_verified_creators(
            env, partner, 98
        ),
    )
    try:
        partner_service = flow["container"].build_bot_services()[
            "partner_view_service"
        ]

        async def current_grade():
            async with flow[
                "container"
            ].transaction_manager.transaction() as db:
                view = await partner_service.view(
                    flow["partner"],
                    platform="telegram",
                    writes_paused=False,
                    session=db,
                )
                return view["grade"]

        # The actual assigned creator is the 99th verified direct referral.
        paid_count = await count_at(
            env["pg"], flow["partner"], flow["receipt"].protocol_message_at
        )
        assert paid_count.verified_count == 99
        before = await current_grade()
        assert before["verified_creators"] == 99
        assert before["tier_rate_bps"] == 1000
        crossed_at = add_verified_creators(env, flow["partner"], 1)
        assert (
            await count_at(env["pg"], flow["partner"], crossed_at)
        ).verified_count == 100
        after = await current_grade()
        assert after["verified_creators"] == 100
        assert after["tier_rate_bps"] == 1200
        assert after["threshold"] == 100

        # No work event was consumed before the grade increase.
        await finish_work(env, flow)
        await process_work_events(env, flow)
        earned = obligations(env)
        creator = next(r for r in earned if r["kind"] == "creator_referral")
        clients = [r for r in earned if r["kind"] == "client_referral"]
        assert len(clients) == 2
        snapshots = Base.metadata.tables["rate_snapshots"]
        with Session(env["pg"]) as db:
            creator_snapshot = (
                db.execute(
                    select(snapshots).where(
                        snapshots.c.id == creator["snapshot_id"]
                    )
                )
                .mappings()
                .one()
            )
            client_snapshots = (
                db.execute(
                    select(snapshots).where(
                        snapshots.c.id.in_([r["snapshot_id"] for r in clients])
                    )
                )
                .mappings()
                .all()
            )
        assert (
            creator_snapshot["effective_at"]
            == flow["receipt"].protocol_message_at
        )
        assert creator_snapshot["verified_count"] == 99
        assert creator_snapshot["rate_bps"] == 1000
        assert {r["rate_bps"] for r in client_snapshots} == {1000}
        assert {r["verified_count"] for r in client_snapshots} == {None}
        assert wallet(env, flow["partner"])["hold_minor"] == 5000
        assert wallet(env, flow["partner"])["pending_minor"] == 10000
    finally:
        await flow["container"].dispose()
