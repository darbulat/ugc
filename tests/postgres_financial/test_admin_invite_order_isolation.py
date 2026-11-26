"""Manual entry works across customers and order sizes without scoped state."""

from datetime import timedelta
from re import search
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramForbiddenError
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_user,
)
from tests.postgres_financial.test_creator_social import seed_profile
from tests.postgres_financial.test_invite_partners import partner, work_manager
from tests.postgres_financial.test_order_intake import Clock
from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine,
    intake_env,
    paid_order,
)
from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
)
from ugc_bot.admin.order_progress import OrderProgress, load_order_progress
from ugc_bot.admin.order_worklist import worklist_row_details
from ugc_bot.domain.order_display import public_order_number
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.invite_handoff_models import NOTICES
from ugc_bot.infrastructure.db.invite_partner_models import PARTNERS
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    FinancialMovementModel,
    FinancialPolicyVersionModel,
    ManagerOrderModel,
    OrderItemModel,
    UserModel,
    UserReferralBindingModel,
)

__all__ = ["financial_pg_engine", "intake_env"]


async def another_customer(env):
    user = await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        country="ru",
    )
    await create_test_advertiser_profile(
        env["repos"]["advertiser_repo"], user.user_id
    )
    version = "isolated-customer-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=env["admin"].user_id,
                approved_at=env["clock"].now() - timedelta(days=2),
                effective_from=env["clock"].now() - timedelta(days=1),
                refund_window_seconds=3600,
                rules={
                    "terms_reference": "synthetic-approved-terms",
                    "allowed_clients": [str(user.user_id)],
                },
            )
        )
    return dict(env, user=user, policy=version, clock=Clock())


def people_and_positions(env, order_ids, sizes, handle, kind):
    with Session(env["pg"]) as db, db.begin():
        referrer = partner(db)
        managers = [partner(db), partner(db)]
        for manager in managers:
            work_manager(db, manager, env["clock"].now())
        if kind != "external":
            creator = seed_profile(db, stable_id=uuid4().hex)
            user = db.get(UserModel, creator)
            user.telegram = handle
            user.telegram_id = str(uuid4().int % 10**12 + 1)
            user.status = "bot_blocked" if kind == "blocked" else "active"
            db.get(
                BloggerProfileModel, creator
            ).instagram_url = f"https://instagram.com/{handle}"
            db.add(
                UserReferralBindingModel(
                    referred_user_id=creator,
                    referrer_user_id=referrer,
                    created_at=env["clock"].now(),
                )
            )
        items = [
            db.scalar(
                select(OrderItemModel.paid_item_id).where(
                    OrderItemModel.order_id == oid,
                    OrderItemModel.ordinal == size,
                )
            )
            for oid, size in zip(order_ids, sizes, strict=True)
        ]
        baseline = db.scalar(
            select(func.count()).select_from(FinancialMovementModel)
        )
    return referrer, managers, items, baseline


def fake_telegram(monkeypatch, second_chat, outcome):
    def send(**kwargs):
        if kwargs["chat_id"] == second_chat:
            if outcome == "failed":
                raise TelegramForbiddenError(method=None, message="blocked")
            if outcome == "unknown":
                raise TimeoutError("synthetic provider timeout")
        return SimpleNamespace(message_id=1)

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=send))

    monkeypatch.setattr("aiogram.Bot.send_message", bot.send_message)
    return bot


def admin_client(env, monkeypatch):
    from ugc_bot.admin.app import create_admin_app

    for key, value in {
        "DATABASE_URL": env["pg"].url.render_as_string(hide_password=False),
        "BOT_TOKEN": "123456789:TEST_ONLY_TOKEN_FOR_ISOLATED_CASES",
        "ADMIN_USERNAME": "test_admin",
        "ADMIN_PASSWORD": "test_pass",
        "ADMIN_SECRET": "test_secret",
        "FINANCIAL_CORE_ENABLED": "true",
        "CUSTOMER_WORKFLOWS_ENABLED": "true",
        "TELEGRAM_BOT_USERNAME": "example_test_bot",
    }.items():
        monkeypatch.setenv(key, value)
    return TestClient(create_admin_app())


async def assert_separate_counters(env, order_ids, counts):
    thresholds = DelayThresholds(7, 24, 48, 30)
    with Session(env["pg"]) as db:
        progress = load_order_progress(db, order_ids)
        worklist = worklist_row_details(db, order_ids, thresholds)
        for oid, count in zip(order_ids, counts, strict=True):
            assert progress[oid] == OrderProgress(count, count, count)
            assert worklist[oid]["picked"] == count
            assert worklist[oid]["transferred_count"] == count
            assert worklist[oid]["manual_transferred_count"] == count
    dashboard = AdminDashboardService(
        env["container"].session_factory, "Europe/Moscow", thresholds
    )
    for oid, count in zip(order_ids, counts, strict=True):
        listed = await dashboard.list_orders("all", search=str(oid))
        row = next(r for r in listed["items"] if r["order_id"] == str(oid))
        assert row["transferred_count"] == count
        assert row["manual_transferred_count"] == count
        assert row["picked_count"] == count
        activity = await dashboard.get_order_workspace_activity(
            oid, can_send=True
        )
        assert activity["workspace"]["transfer_count"] == count
        assert activity["workspace"]["manual_count"] == count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sizes,kind,second_outcome",
    [
        ((10, 20), "external", "sent"),
        ((20, 30), "ready", "sent"),
        ((30, 10), "blocked", "sent"),
        ((10, 30), "external", "sent"),
        ((50, 200), "external", "sent"),
        ((100, 10), "ready", "sent"),
        ((20, 10), "external", "failed"),
        ((20, 10), "external", "unknown"),
    ],
)
async def test_manual_handoffs_remain_correct_across_two_customer_orders(
    intake_env, monkeypatch, sizes, kind, second_outcome
):
    env = intake_env
    other = await another_customer(env)
    _, first, _, _, _ = await paid_order(
        env, size=sizes[0], interested_creators=0
    )
    _, second, _, _, _ = await paid_order(
        other, size=sizes[1], interested_creators=0
    )
    order_ids = [first, second]
    handle = "author_" + uuid4().hex[:16]
    referrer, managers, items, baseline = people_and_positions(
        env, order_ids, sizes, handle, kind
    )
    bot = fake_telegram(
        monkeypatch, int(other["user"].telegram_id), second_outcome
    )
    forms, identities = [], []
    paths = [f"/admin/orders/{oid}/creator-invites" for oid in order_ids]
    with admin_client(env, monkeypatch) as client:
        client.post(
            "/admin/login",
            data={"username": "test_admin", "password": "test_pass"},
        )
        for path, item, manager in zip(paths, items, managers, strict=True):
            page = client.get(path)
            assert page.status_code == 200
            forms.append(
                dict(
                    csrf_token=search(
                        r'name="csrf_token" value="([^"]+)"', page.text
                    )[1],
                    item_id=str(item),
                    instagram=f"@{handle}",
                    telegram=f"@{handle}",
                    creator_name="Тестовый автор",
                    record_consent="1",
                    consent_source="telegram",
                    manager_id=str(manager),
                    referrer_id=str(referrer),
                    operation="send_customer",
                )
            )
        wrong = client.post(
            paths[0], data=forms[0] | {"item_id": str(items[1])}
        )
        assert "Позиция уже недоступна" in wrong.text
        assert 'id="invite-result"' not in wrong.text
        bot.send_message.assert_not_awaited()
        with Session(env["pg"]) as db:
            assert db.scalar(select(func.count()).select_from(INVITES)) == 0
            assert (
                db.scalar(select(func.count()).select_from(ManagerOrderModel))
                == 0
            )

        for index, (path, form, oid, size) in enumerate(
            zip(paths, forms, order_ids, sizes, strict=True)
        ):
            result = client.post(path, data=form)
            assert result.status_code == 200
            sent = index == 0 or second_outcome == "sent"
            assert ('id="invite-result"' in result.text) == sent
            if sent:
                assert [r.status_code for r in result.history] == [303]
                assert f"Позиция №{size} из {size}" in result.text
            else:
                assert not result.history
                assert "Контакт отправлен заказчице" not in result.text
            call = bot.send_message.await_args_list[index].kwargs
            owner = env["user"] if index == 0 else other["user"]
            assert call["chat_id"] == int(owner.telegram_id)
            assert public_order_number(oid) in call["text"]
            assert public_order_number(order_ids[1 - index]) not in call["text"]
            assert f"Позиция №{size} из {size}" in call["text"]
            with Session(env["pg"]) as db:
                identity = db.scalar(
                    select(INVITES.c.id).where(INVITES.c.order_id == oid)
                )
                identities.append(identity)
            client.post(path, data=form)
            assert bot.send_message.await_count == index + 1

        for index, path in enumerate(paths):
            foreign = client.get(
                path, params={"sent": str(identities[1 - index])}
            )
            assert 'id="invite-result"' not in foreign.text
    assert bot.send_message.await_count == 2
    with Session(env["pg"]) as db:
        assert db.scalar(select(func.count()).select_from(INVITES)) == 2
        assert (
            db.scalar(select(func.count()).select_from(FinancialMovementModel))
            == baseline
        )
        for index, (oid, identity) in enumerate(
            zip(order_ids, identities, strict=True)
        ):
            row = (
                db.execute(select(INVITES).where(INVITES.c.id == identity))
                .mappings()
                .one()
            )
            assert row["manager_id"] == managers[index]
            assert db.get(ManagerOrderModel, (managers[index], oid)) is not None
            assert db.get(ManagerOrderModel, (managers[1 - index], oid)) is None
            assert (
                db.scalar(
                    select(PARTNERS.c.referrer_id).where(
                        PARTNERS.c.invite_id == identity
                    )
                )
                == referrer
            )
            assert db.scalar(
                select(NOTICES.c.state).where(
                    NOTICES.c.invite_id == identity,
                    NOTICES.c.kind == "customer",
                )
            ) == ("sent" if index == 0 else second_outcome)
    await assert_separate_counters(
        env, order_ids, [1, 1 if second_outcome == "sent" else 0]
    )
