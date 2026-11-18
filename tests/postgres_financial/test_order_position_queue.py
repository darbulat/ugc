"""The queue distinguishes pending invites, empty slots and delivery proof."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts.prepare_invite_preview_order import provision
from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine as financial_pg_engine,
)
from tests.postgres_financial.test_telegram_order_summary import (
    intake_env as intake_env,
)
from tests.postgres_financial.test_telegram_order_summary import paid_order
from ugc_bot.admin.order_review import _load_review
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.campaign_summary_service import (
    CampaignSummaryService,
)
from ugc_bot.container.creator_invite_factory import build_creator_invites
from ugc_bot.infrastructure.db.models import (
    ManagerOrderModel,
    OrderItemModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.campaign_summary import (
    SqlAlchemyCampaignSummaryRepository,
)
from ugc_bot.infrastructure.db.repositories.creator_invites import create_invite
from ugc_bot.infrastructure.db.repositories.order_position_queue import (
    queue_rows,
)
from ugc_bot.miniapp.campaign_summary_api import create_campaign_summary_router
from ugc_bot.miniapp.manager_position_queue import (
    create_manager_position_queue_router,
)

__all__ = ["financial_pg_engine", "intake_env"]

PREVIEW_ORDER = UUID("e0828ce4-f2c3-429e-afb1-f97e27fdb3b8")


def link_to_manager(db, env, order, at):
    db.add(
        ManagerOrderModel(
            order_id=order, user_id=env["admin"].user_id, created_at=at
        )
    )
    db.flush()
    return db.scalars(
        select(OrderItemModel.paid_item_id)
        .where(OrderItemModel.order_id == order)
        .order_by(OrderItemModel.ordinal)
    ).all()


@pytest.mark.asyncio
async def test_preview_stages_and_order_scoped_manager_endpoint(
    intake_env, monkeypatch
):
    env = intake_env
    engine, oid = env["pg"], PREVIEW_ORDER
    now = datetime.now(timezone.utc)
    manager_external_id = str(uuid4().int % 10**12 + 1)
    with Session(engine) as db, db.begin():
        db.get(UserModel, env["user"].user_id).telegram = "queue_owner"
        db.get(
            UserModel, env["admin"].user_id
        ).telegram_id = manager_external_id
        provision(db, oid, "queue_owner")
        one, two = link_to_manager(db, env, oid, now)
        assert not queue_rows(db, now)
        baseline = queue_rows(db, now, oid, stage="manual")
        assert [row["ordinal"] for row in baseline] == [1, 2]
        assert all(row["preview"] for row in baseline)
        create_invite(
            db, oid, one, None, "@queue_wait", now, telegram="@queue_wait"
        )
        create_invite(
            db,
            oid,
            two,
            None,
            "@queue_ready",
            now,
            telegram="@queue_ready",
            consent_source="telegram",
        )
    admin, more = _load_review(
        engine, oid, env["admin"].user_id, False, 1, at=now, stage="all"
    )
    assert not more
    assert [position["stage"] for position in admin[0]["positions"]] == [
        "waiting",
        "received",
    ]
    assert not admin[0]["positions"][1]["entries"]

    async def resolve(request, data, *, platform):
        if data not in {"manager", "customer"}:
            raise HTTPException(401)
        return env["admin" if data == "manager" else "user"]

    app = FastAPI()
    app.state.dispatcher = {
        "container": SimpleNamespace(get_admin_engine=lambda: engine),
        "campaign_summary_service": CampaignSummaryService(
            SqlAlchemyCampaignSummaryRepository(),
            env["container"].transaction_manager,
            env["clock"],
        ),
    }
    app.include_router(create_manager_position_queue_router(resolve))

    async def resolve_summary(request, data, *, platform):
        if data == "manager":
            return AuthenticatedMessengerPrincipal(
                env["admin"].user_id, platform, manager_external_id
            )
        if data == "customer":
            user = env["user"]
            return AuthenticatedMessengerPrincipal(
                user.user_id, platform, user.telegram_id
            )
        raise HTTPException(401, "financial_session_invalid")

    app.include_router(create_campaign_summary_router(resolve_summary))
    path = f"/manager/orders/{oid}/position-queue"
    with TestClient(app) as web:
        assert web.post(path, json={"init_data": "invalid"}).status_code == 401
        assert web.post(path, json={"init_data": "customer"}).status_code == 404
        assert (
            web.post(
                f"/manager/orders/{uuid4()}/position-queue",
                json={"init_data": "manager"},
            ).status_code
            == 404
        )
        assert (
            web.post(
                path,
                json={
                    "init_data": "manager",
                    "platform": "max",
                },
            ).status_code
            == 404
        )
        result = web.post(
            path, json={"init_data": "manager", "stage": "waiting"}
        )
        assert result.headers["cache-control"] == "no-store"
        assert result.json() == {
            "positions": [
                {
                    "ordinal": 1,
                    "stage": "waiting",
                    "label": "Ждём ответа",
                    "needs_review": False,
                    "preview": True,
                }
            ]
        }
        assert "queue_ready" not in result.text
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as web:
        path = f"/orders/{oid}/campaign-summary"
        owner_summary = await web.post(path, json={"init_data": "customer"})
        assert owner_summary.status_code == 200, owner_summary.text
        assert owner_summary.headers["cache-control"] == "no-store"
        assert owner_summary.json()["source"] == "invite_preview"
        assert owner_summary.json()["creator_contacts"] == [
            {"ordinal": 1, "instagram": None, "telegram": None},
            {
                "ordinal": 2,
                "instagram": "@queue_ready",
                "telegram": "@queue_ready",
            },
        ]
        manager_summary = await web.post(path, json={"init_data": "manager"})
        assert manager_summary.status_code == 200, manager_summary.text
        assert "creator_contacts" not in manager_summary.json()
        assert (
            await web.post(path, json={"init_data": "invalid"})
        ).status_code == 401

    from ugc_bot.admin.app import create_admin_app

    for key, value in {
        "DATABASE_URL": engine.url.render_as_string(hide_password=False),
        "ADMIN_USERNAME": "test_admin",
        "ADMIN_PASSWORD": "test_pass",
        "ADMIN_SECRET": "test_secret",
    }.items():
        monkeypatch.setenv(key, value)
    with TestClient(create_admin_app()) as admin_web:
        admin_web.post(
            "/admin/login",
            data={"username": "test_admin", "password": "test_pass"},
            follow_redirects=False,
        )
        path = f"/admin/order-review?order_id={oid}"
        page = admin_web.get(path + "&stage=received")
        assert page.status_code == 200
        assert "В предпросмотре" in page.text
        assert "Тестовый заказ" in page.text
        assert "Подбор до" in page.text
        assert 'aria-current="page"' in page.text
        assert (
            "В предпросмотре" not in admin_web.get(path + "&stage=waiting").text
        )


@pytest.mark.asyncio
async def test_paid_position_waits_for_receipt_and_expired_invite_is_manual(
    intake_env,
):
    env = intake_env
    summary, oid, _, client, bot = await paid_order(env, interested_creators=0)
    engine, at = env["pg"], env["clock"].now()
    with Session(engine) as db, db.begin():
        one, two, *_ = link_to_manager(db, env, oid, at)
        create_invite(
            db, oid, one, None, "@queue_expired", at - timedelta(days=31)
        )
        identity = create_invite(
            db,
            oid,
            two,
            None,
            "@queue_delivered",
            at,
            telegram="@queue_delivered",
            consent_source="telegram",
        )
        rows = queue_rows(db, at, oid)
        assert [row["stage"] for row in rows[:2]] == ["manual", "waiting"]
        assert not rows[1]["preview"]
    service = build_creator_invites(summary.transactions)
    service.clock = env["clock"]
    campaign = CampaignSummaryService(
        SqlAlchemyCampaignSummaryRepository(),
        summary.transactions,
        env["clock"],
    )
    before = await campaign.view(oid, client.user_id, principal=client)
    assert before["creator_contacts"] == []
    await service.acknowledge_staff_contact(client, identity)
    after = await campaign.view(oid, client.user_id, principal=client)
    assert after["creator_contacts"] == [
        {
            "ordinal": 2,
            "instagram": "@queue_delivered",
            "telegram": "@queue_delivered",
        }
    ]
    with Session(engine) as db:
        rows = queue_rows(db, at, oid, stage="received")
        assert [row["paid_item_id"] for row in rows] == [two]
    bot.send_message.assert_not_awaited()
