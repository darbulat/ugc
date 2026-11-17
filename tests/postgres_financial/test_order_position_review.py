"""Staff queue and receipt handling against the paid-position schema."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.helpers.factories import create_test_user
from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine as financial_pg_engine,
)
from tests.postgres_financial.test_telegram_order_summary import (
    intake_env as intake_env,
)
from tests.postgres_financial.test_telegram_order_summary import (
    paid_order,
    seed_pending_referrals,
)
from ugc_bot.admin.order_review import _load_review
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.db.collaboration_models import CollaborationModel
from ugc_bot.infrastructure.db.customer_workflow_models import REQUESTS
from ugc_bot.infrastructure.db.models import (
    ItemAssignmentModel,
    ManagerOrderModel,
    OrderItemModel,
)
from ugc_bot.infrastructure.db.order_review_models import ALERTS
from ugc_bot.infrastructure.db.paid_selection_models import JOBS
from ugc_bot.infrastructure.db.repositories.order_review import (
    position_review_count_query,
    set_position_manager,
)
from ugc_bot.order_review_scheduler import run_once

__all__ = ["financial_pg_engine", "intake_env"]


async def new_staff(env, *, admin=False):
    return await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        admin=admin,
    )


@pytest.mark.asyncio
async def test_paid_positions_queue_and_deadline_alerts(
    intake_env, monkeypatch
):
    env = intake_env
    summary, oid, interests, _, bot = await paid_order(
        env, interested_creators=2
    )
    duty = env["admin"]
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "ORDER_REVIEW_ALERTS_START_AT": env["clock"].now().isoformat(),
            "ORDER_REVIEW_DUTY_ADMIN_ID": str(duty.user_id),
        }
    )
    assert config.order.order_review_duty_admin_id == duty.user_id
    manager, other_manager, unrelated_admin = await asyncio.gather(
        new_staff(env), new_staff(env), new_staff(env, admin=True)
    )
    with Session(env["pg"]) as db, db.begin():
        items = db.scalars(
            select(OrderItemModel)
            .where(OrderItemModel.order_id == oid)
            .order_by(OrderItemModel.ordinal)
        ).all()
        first, second = items[2:4]
        item_id, deadline = first.paid_item_id, first.selection_due_at
        second_id = second.paid_item_id
        db.add_all(
            ManagerOrderModel(
                order_id=oid,
                user_id=user.user_id,
                created_at=env["clock"].now(),
            )
            for user in (manager, other_manager, env["user"])
        )
        db.flush()
        clock_at = deadline - timedelta(hours=24)

        assert "активного менеджера" in set_position_manager(
            db, oid, item_id, env["user"].user_id, None, clock_at
        )
        assert "сохранён" in set_position_manager(
            db, oid, item_id, manager.user_id, None, clock_at
        )
        assert "изменился" in set_position_manager(
            db, oid, item_id, other_manager.user_id, None, clock_at
        )
        assert "сохранён" in set_position_manager(
            db, oid, second_id, manager.user_id, None, clock_at
        )

    clock, engine = env["clock"], env["pg"]
    start_at = config.order.order_review_alerts_start_at
    assert start_at == clock.now()
    clock.at = deadline - timedelta(hours=24, seconds=1)
    transport = SimpleNamespace(
        send=AsyncMock(return_value=DeliveryReceipt("telegram", "received"))
    )
    args = (
        engine,
        transport,
        clock,
        start_at,
        duty.user_id,
        "https://admin.example.test",
    )

    await run_once(*args)
    transport.send.assert_not_awaited()
    with Session(engine) as db:
        assert db.scalar(position_review_count_query(clock.now())) == 0

    clock.at += timedelta(seconds=1)
    await run_once(
        engine,
        transport,
        clock,
        clock.now() + timedelta(seconds=1),
        duty.user_id,
        args[-1],
    )
    transport.send.assert_not_awaited()
    await run_once(*args)
    await run_once(*args)
    messages = {
        call.args[0].address: call.args[0].text
        for call in transport.send.await_args_list
    }
    assert transport.send.await_count == 2
    assert set(messages) == {duty.telegram_id, manager.telegram_id}
    assert unrelated_admin.telegram_id not in messages
    assert env["user"].telegram_id not in messages
    assert "8." in messages[duty.telegram_id]
    assert f"/admin/order-review?order_id={oid}" in messages[duty.telegram_id]
    assert "Ваши позиции: 3, 4." in messages[manager.telegram_id]
    assert "ближайшие 24 часа" in messages[duty.telegram_id]

    transport.send.reset_mock()
    clock.at = deadline
    transport.send.side_effect = DeliveryFailure("test_unknown", uncertain=True)
    await run_once(*args)
    await run_once(*args)
    assert transport.send.await_count == 2
    assert all(
        "Срок подбора истёк" in call.args[0].text
        for call in transport.send.await_args_list
    )
    with Session(engine) as db:
        alerts = db.execute(
            select(ALERTS.c.stage, ALERTS.c.state).where(
                ALERTS.c.order_id == oid
            )
        ).all()
        assert (
            sorted(alerts)
            == [("overdue", "unknown")] * 2 + [("upcoming", "accepted")] * 2
        )

    # Read the same projection used by the admin page.
    orders, more = _load_review(
        engine, oid, manager.user_id, False, 1, at=clock.now()
    )
    assert not more
    assert [p["ordinal"] for p in orders[0]["positions"]] == [3, 4]
    assert (orders[0]["used"], orders[0]["left"]) == (0, 2)
    assert orders[0]["positions"][0]["reason"] == "Нужно подобрать креатора"

    # A separate existing workflow can still be used to collect exception data.
    # Its old broad deadline notification must not duplicate the staff alert.
    summary.staff_alerts_start_at = args[3]
    async with summary.transactions.transaction() as db:
        await summary.summaries.card(
            oid, env["user"].user_id, clock.now(), session=db, lock=True
        )
    await summary.close_if_resolved(oid, env["user"].user_id)
    with Session(engine) as db:
        assert (
            db.scalar(
                select(REQUESTS.c.request_id).where(REQUESTS.c.order_id == oid)
            )
            is None
        )
    bot.send_message.assert_not_awaited()

    from ugc_bot.admin import app as admin_app
    from ugc_bot.admin import order_review as review_page

    real_now = review_page.datetime

    class ReviewTime(real_now):
        @classmethod
        def now(cls, tz=None):
            return clock.now().astimezone(tz)

    monkeypatch.setattr(review_page, "datetime", ReviewTime)
    monkeypatch.setenv(
        "DATABASE_URL", engine.url.render_as_string(hide_password=False)
    )
    monkeypatch.setenv("ADMIN_USERNAME", "test_admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test_pass")
    monkeypatch.setenv("ADMIN_SECRET", "test_secret")
    monkeypatch.setenv("USE_REDIS_STORAGE", "false")
    web = TestClient(admin_app.create_admin_app())
    path = f"/admin/order-review?order_id={oid}"
    assert (
        web.get(path, follow_redirects=False).headers["location"]
        == "/admin/login"
    )
    web.post(
        "/admin/login",
        data={"username": "test_admin", "password": "test_pass"},
        follow_redirects=False,
    )
    page = web.get(path)
    assert page.status_code == 200
    assert page.text.count("Нужно подобрать креатора") == 8
    assert "Просрочено" in page.text
    assert "осталось 2 из 2" in page.text
    dashboard_queue = web.get(path, params={"include_unpicked": "false"})
    assert dashboard_queue.status_code == 200
    assert "По этим фильтрам позиций нет." in dashboard_queue.text
    with Session(engine) as db:
        assert db.scalar(position_review_count_query(clock.now())) == 0
    import re

    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    action = f"/admin/order-review/{oid}/{item_id}/assign"
    fields = {
        "expected": str(manager.user_id),
        "manager_id": str(other_manager.user_id),
    }
    assert web.post(action, data=fields).status_code == 403
    saved = web.post(action, data=fields | {"csrf_token": csrf})
    assert "Ответственный сохранён" in saved.text

    await seed_pending_referrals(summary, env, oid, interests[:1])
    from ugc_bot.infrastructure.db.repositories.order_review import (
        referral_entries,
    )

    with Session(engine) as db:
        (entry,) = referral_entries(db, [interests[0].paid_item_id])
        assert entry.pending == entry.amount_minor
        assert entry.paid == 0


@pytest.mark.asyncio
async def test_dashboard_review_keeps_contact_and_work_problems(intake_env):
    env = intake_env
    _, oid, interests, _, _ = await paid_order(
        env, interested_creators=4, deliver_contacts=False
    )
    engine = env["pg"]
    with Session(engine) as db, db.begin():
        deadline = db.scalar(
            select(OrderItemModel.selection_due_at)
            .where(OrderItemModel.order_id == oid)
            .limit(1)
        )
        early = deadline - timedelta(hours=25)
        db.execute(
            update(JOBS)
            .where(JOBS.c.interest_id == interests[1].interest_id)
            .values(state="failed")
        )
        for interest, state in zip(
            interests[2:], ("disputed", "in_progress"), strict=True
        ):
            assignment = db.get(ItemAssignmentModel, interest.assignment_id)
            db.add(
                CollaborationModel(
                    assignment_id=assignment.assignment_id,
                    paid_item_id=assignment.paid_item_id,
                    order_id=oid,
                    currency="RUB",
                    client_id=env["user"].user_id,
                    creator_id=assignment.creator_id,
                    policy_version=env["policy"],
                    state=state,
                    version=1,
                    due_at=early if state == "in_progress" else deadline,
                    record_payload={},
                    updated_at=early,
                )
            )

    for at, ordinals in (
        (early, [2, 3, 4]),
        (deadline - timedelta(hours=24), [1, 2, 3, 4]),
    ):
        orders, more = _load_review(
            engine, oid, None, False, 1, at=at, include_unpicked=False
        )
        assert not more
        assert [row["ordinal"] for row in orders[0]["positions"]] == ordinals
        with Session(engine) as db:
            assert db.scalar(position_review_count_query(at)) == len(ordinals)
