"""Current native identities bind extended intake and observed funnel stages."""

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_order_intake_api import app, body
from tests.postgres_financial.test_order_intake_api import (
    intake_env as intake_env_fixture,
)
from ugc_bot.config import MaxBotConfig
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import OrderModel, UserModel
from ugc_bot.infrastructure.db.order_funnel_models import FUNNEL

intake_env = intake_env_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_native_extended_intake_and_funnel_report_current_authority(
    intake_env, platform
):
    env = intake_env
    if platform == "max":
        env["config"].max_bot = MaxBotConfig(MAX_BOT_TOKEN="max-test-token")
        with Session(env["pg"]) as db, db.begin():
            for user in (env["user"], env["admin"]):
                db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == user.user_id)
                    .values(max_id=user.telegram_id)
                )
    payload = body(env, platform)
    auth = {key: payload[key] for key in ("init_data", "platform")}
    funnel = uuid4()
    targeting = dict(
        min_followers=1000,
        max_followers=20000,
        min_age=18,
        max_age=40,
        gender="f",
        city=" Москва ",
        platforms=["youtube", "tiktok"],
        content_usage="Short vertical review",
        brief_link="https://example.com/brief",
    )
    payload.update(targeting=targeting, funnel_id=str(funnel))
    prefix = "/miniapp/api/financial/orders"
    native_app = app(env, env["container"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=native_app), base_url="http://test"
    ) as client:
        for stage in ("opened", "brief", "filters", "package", "package"):
            response = await client.post(
                prefix + "/funnel/stage",
                json=dict(auth, funnel_id=str(funnel), stage=stage),
            )
            assert response.status_code == 200 and response.json() == {
                "recorded": True
            }
            assert response.headers["cache-control"] == "no-store"
        response = await client.post(prefix, json=payload)
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["targeting"] == dict(
            targeting, city="Москва", platforms=["tiktok", "youtube"]
        )
        assert (await client.post(prefix, json=payload)).json() == receipt
        with Session(env["pg"]) as db:
            order = db.get(OrderModel, UUID(receipt["order_id"]))
            assert (
                order.min_followers,
                order.max_followers,
                order.min_age,
                order.max_age,
            ) == (1000, 20000, 18, 40)
            assert str(order.required_blogger_gender) == "f"
            assert (order.geography, order.content_usage, order.brief_link) == (
                "Москва",
                targeting["content_usage"],
                targeting["brief_link"],
            )
            observed = (
                db.execute(
                    select(FUNNEL).where(
                        FUNNEL.c.client_id == env["user"].user_id,
                        FUNNEL.c.funnel_id == funnel,
                    )
                )
                .mappings()
                .all()
            )
            saved = db.scalar(
                select(
                    Base.metadata.tables["order_intake_receipts"].c.result
                ).where(
                    Base.metadata.tables["order_intake_receipts"].c.order_id
                    == order.order_id
                )
            )
        assert saved["targeting"] == receipt["targeting"]
        assert {row["stage"] for row in observed} == {
            "opened",
            "brief",
            "filters",
            "package",
            "created",
        }
        assert len(observed) == 5
        created = next(row for row in observed if row["stage"] == "created")
        assert str(created["order_id"]) == receipt["order_id"]
        assert (
            await client.post(prefix + "/funnel/report", json=auth)
        ).status_code == 403
        admin_auth = dict(
            init_data=generate_init_data(
                "test-token" if platform == "telegram" else "max-test-token",
                int(env["admin"].telegram_id),
                "admin",
            ),
            platform=platform,
        )
        report = await client.post(prefix + "/funnel/report", json=admin_auth)
        assert report.status_code == 200, report.text
        assert report.json()["client_stages_are_observations"] is True
        assert report.json()["actual_orders"] >= 1
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["admin"].user_id)
                .values(admin=False)
            )
        revoked = await client.post(prefix + "/funnel/report", json=admin_auth)
        assert (
            revoked.status_code == 403
            and revoked.json()["detail"] == "intake_admin_required"
        )
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["user"].user_id)
                .values(status="blocked")
            )
        blocked = await client.post(
            prefix + "/funnel/stage",
            json=dict(auth, funnel_id=str(uuid4()), stage="opened"),
        )
        assert (
            blocked.status_code == 403
            and blocked.json()["detail"] == "active_advertiser_required"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "targeting",
    [
        {"min_age": True},
        {"min_age": 30, "max_age": 20},
        {"city": "  "},
        {"platforms": ["youtube", "youtube"]},
        {"platforms": ["invented"]},
        {"brief_link": "javascript:PRIVATE()"},
        {"brief_link": "https://PRIVATE:secret@example.com/brief"},
        {"content_usage": " "},
        {"min_followers": "1000"},
        {"manager_id": "PRIVATE"},
    ],
)
async def test_native_intake_rejects_invalid_extended_filters_without_writes(
    intake_env, targeting
):
    env = intake_env
    payload = body(env)
    payload["targeting"] = targeting
    receipts = Base.metadata.tables["order_intake_receipts"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(env, env["container"])),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/miniapp/api/financial/orders", json=payload
        )
    assert response.status_code == 422
    assert response.json() == {"detail": "intake_request_invalid"}
    assert "PRIVATE" not in response.text
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(receipts.c.order_id).where(
                    receipts.c.client_id == env["user"].user_id,
                    receipts.c.operation_key == payload["operation_key"],
                )
            )
            is None
        )


@pytest.mark.asyncio
async def test_funnel_api_cannot_forge_created_actor_or_unauthenticated_event(
    intake_env,
):
    env = intake_env
    payload = body(env)
    auth = {key: payload[key] for key in ("init_data", "platform")}
    stage = dict(auth, funnel_id=str(uuid4()), stage="opened")
    path = "/miniapp/api/financial/orders/funnel/stage"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(env, env["container"])),
        base_url="http://test",
    ) as client:
        for invalid in (
            dict(stage, stage="created"),
            dict(stage, client_id=str(env["admin"].user_id)),
            dict(stage, funnel_id=str(UUID(int=0))),
        ):
            response = await client.post(path, json=invalid)
            assert response.status_code == 422
        assert (
            await client.post(path + "?actor=PRIVATE", json=stage)
        ).status_code == 422
        assert (
            await client.post(path, json=dict(stage, init_data="invalid"))
        ).status_code == 401
        services = client._transport.app.state.dispatcher
        services["order_intake_service"] = None
        assert (await client.post(path, json=stage)).status_code == 503
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(FUNNEL.c.client_id).where(
                    FUNNEL.c.client_id == env["user"].user_id
                )
            )
            is None
        )
