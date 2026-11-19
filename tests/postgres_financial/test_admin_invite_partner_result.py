"""Persist independent selections and show only provider-confirmed success."""

from re import search
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.postgres_financial.test_invite_partners import partner, work_manager
from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine,
    intake_env,
    paid_order,
)
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.invite_handoff_models import NOTICES
from ugc_bot.infrastructure.db.invite_partner_models import PARTNERS
from ugc_bot.infrastructure.db.models import ManagerOrderModel

__all__ = ["financial_pg_engine", "intake_env"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome", ["sent", "failed", "unknown", "invalid_referrer"]
)
async def test_admin_result_preserves_actual_position_and_partner(
    intake_env, monkeypatch, outcome
):
    from ugc_bot.admin.app import create_admin_app

    env = intake_env
    _, oid, _, _, _ = await paid_order(env, interested_creators=0)
    for key, value in {
        "DATABASE_URL": env["pg"].url.render_as_string(hide_password=False),
        "BOT_TOKEN": "test-token",
        "ADMIN_USERNAME": "test_admin",
        "ADMIN_PASSWORD": "test_pass",
        "ADMIN_SECRET": "test_secret",
        "FINANCIAL_CORE_ENABLED": "true",
        "CUSTOMER_WORKFLOWS_ENABLED": "true",
        "TELEGRAM_BOT_USERNAME": "example_test_bot",
    }.items():
        monkeypatch.setenv(key, value)
    with Session(env["pg"]) as db, db.begin():
        manager, referrer = partner(db), partner(db)
        work_manager(db, manager, env["clock"].now())

    async def dispatch(config, service, identity):
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                NOTICES.insert().values(
                    invite_id=identity, kind="customer", state=outcome
                )
            )
        return outcome

    send = AsyncMock(side_effect=dispatch)
    monkeypatch.setattr(
        "ugc_bot.admin.creator_invites.dispatch_customer_contact", send
    )
    path = f"/admin/orders/{oid}/creator-invites"
    with TestClient(create_admin_app()) as client:
        client.post(
            "/admin/login",
            data={"username": "test_admin", "password": "test_pass"},
        )
        page = client.get(path)
        token = search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
        result = client.post(
            path,
            data={
                "csrf_token": token,
                "operation": "send_customer",
                "instagram": "@manual_new",
                "telegram": "@manual_new",
                "creator_name": "Тестовый автор",
                "record_consent": "1",
                "consent_source": "telegram",
                "manager_id": str(manager),
                "referrer_id": str(
                    uuid4() if outcome == "invalid_referrer" else referrer
                ),
            },
        )
        assert result.status_code == 200
        if outcome == "invalid_referrer":
            assert "Выберите активного партнёра" in result.text
            send.assert_not_awaited()
            with Session(env["pg"]) as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(INVITES)
                        .where(INVITES.c.order_id == oid)
                    )
                    == 0
                )
                assert db.get(ManagerOrderModel, (manager, oid)) is None
            return
        if outcome == "sent":
            assert [r.status_code for r in result.history] == [303]
            assert "Контакт отправлен заказчице в Telegram" in result.text
            assert "Позиция №1 из 10 · Тестовый автор" in result.text
            assert "Добавить следующего креатора · №2" in result.text
            client.get(str(result.url))
        else:
            assert not result.history
            assert 'id="invite-result"' not in result.text
            assert "Добавить следующего креатора" not in result.text
            assert 'value="@manual_new"' in result.text
            assert "№1 · текущий контакт" in result.text
            assert (
                "invite-outcome--"
                + ("danger" if outcome == "failed" else "warning")
                in result.text
            )
        send.assert_awaited_once()
    with Session(env["pg"]) as db:
        invite = (
            db.execute(select(INVITES).where(INVITES.c.order_id == oid))
            .mappings()
            .one()
        )
        assert invite["manager_id"] == manager
        assert (
            db.scalar(
                select(PARTNERS.c.referrer_id).where(
                    PARTNERS.c.invite_id == invite["id"]
                )
            )
            == referrer
        )
        assert db.get(ManagerOrderModel, (manager, oid)) is not None
        assert db.get(ManagerOrderModel, (referrer, oid)) is None
