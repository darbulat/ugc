"""Exercise Telegram verification, admin review, and private manual contacts."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine,
    intake_env,
    paid_order,
)
from ugc_bot.admin.managers import _directory, _review
from ugc_bot.admin.order_worklist import worklist_manager_suggestions
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.bot.telegram.handlers.order_summary import render_card
from ugc_bot.container.creator_invite_factory import build_creator_invites
from ugc_bot.domain.manager_application import FIELDS
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ManagerOrderModel,
    OrderItemModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.creator_invites import create_invite
from ugc_bot.infrastructure.db.repositories.manager_applications import (
    ManagerApplications,
)
from ugc_bot.miniapp.manager_invites import InviteRequest, manager_invite_data

__all__ = ["financial_pg_engine", "intake_env"]


@pytest.mark.asyncio
async def test_application_verification_review_and_directory(intake_env):
    env = intake_env
    user_id = env["admin"].user_id
    transactions = env["container"].transaction_manager
    graph = SimpleNamespace(
        get_profile_by_id=AsyncMock(
            return_value=SimpleNamespace(username="different_profile")
        )
    )
    service = ManagerApplications(transactions, graph)
    assert (await service.open(user_id))["state"] == "draft"
    with pytest.raises(ValueError, match="пропущенные"):
        await service.submit(user_id)
    answers = dict(
        name="Камиль",
        location="Россия, Казань",
        phone="+70000000000",
        instagram="@test_manager",
        case="Вёл 10 авторов для кафе",
        coverage="Казань",
        settlement="ИП",
        rate="600–800",
        reliability="Предупрежу заранее.",
    )
    assert answers.keys() == FIELDS.keys()
    for field, value in answers.items():
        await service.answer(user_id, field, value)
    await service.submit(user_id)
    await service.submit(user_id)
    with Session(env["pg"]) as db, db.begin():
        with pytest.raises(ValueError, match="Instagram"):
            _review(db, "approved", str(user_id), "")
        _review(db, "clarify", str(user_id), "Уточните загрузку")
    assert (await service.open(user_id))["decision_note"] == "Уточните загрузку"
    await service.answer(user_id, "coverage", "Казань, 10 авторов")
    await service.submit(user_id)
    code = await service.instagram_challenge(user_id)
    assert code == await service.instagram_challenge(user_id)
    assert not await service.verify_instagram(code, "synthetic_instagram_id")
    graph.get_profile_by_id.return_value.username = "test_manager"
    assert await service.verify_instagram(code, "synthetic_instagram_id")
    assert not await service.verify_instagram(code, "synthetic_instagram_id")

    with Session(env["pg"]) as db, db.begin():
        manager = db.get(UserModel, user_id)
        manager.telegram = "test_manager"
        _review(db, "approved", str(user_id), "")
        assert "test_manager" in worklist_manager_suggestions(db)
        rows = _directory(db, "Казань", "available", 0)
        assert [r["user_id"] for r in rows] == [user_id]
    assert await service.approved(user_id)


@pytest.mark.asyncio
async def test_staff_contact_for_own_order_and_manager_notice(intake_env):
    env = intake_env
    order_summary, order_id, _, client, bot = await paid_order(
        env, interested_creators=0
    )
    service = build_creator_invites(order_summary.transactions)
    clock = env["clock"]
    service.clock = service.selection.clock = service.delivery.clock = clock
    manager = env["admin"]
    with Session(env["pg"]) as db, db.begin():
        position = db.scalar(
            select(OrderItemModel).where(
                OrderItemModel.order_id == order_id, OrderItemModel.ordinal == 1
            )
        )
        item = position.paid_item_id
        db.add(
            ManagerOrderModel(
                order_id=order_id,
                user_id=manager.user_id,
                created_at=clock.now(),
            )
        )
    body = InviteRequest(
        init_data="synthetic",
        item_id=item,
        instagram="@from_direct",
        telegram="@direct_creator",
        consent_source="instagram",
        name="Мурат",
    )
    with pytest.raises(PermissionError):
        manager_invite_data(
            env["pg"], client.user_id, order_id, body, "test_bot"
        )
    response = manager_invite_data(
        env["pg"], manager.user_id, order_id, body, "test_bot"
    )
    invite = response["invites"][0]
    identity = invite["id"]
    assert invite["expires_at"] - invite["reported_at"] == timedelta(days=30)
    data = await order_summary.view(client, order_id)
    _, keyboard = render_card(order_summary, data)
    assert any(
        "staff:" in b.callback_data for row in keyboard.rows for b in row
    )
    assert "@direct_creator" in await service.reported_contact_text(
        client, identity
    )
    outsider = AuthenticatedMessengerPrincipal(
        manager.user_id, "telegram", manager.telegram_id
    )
    with pytest.raises(ValueError, match="unavailable"):
        await service.reported_contact_text(outsider, identity)
    assert await service.claim_manager_notice(identity) is None
    assert await service.delivery.run_once() == 0
    bot.send_message.assert_not_awaited()

    with Session(env["pg"]) as db, db.begin():
        with pytest.raises(ValueError, match="position_unavailable"):
            create_invite(
                db,
                order_id,
                item,
                manager.user_id,
                "@another_creator",
                clock.now(),
                telegram="@another_creator",
                consent_source="telegram",
            )
        row = (
            db.execute(select(INVITES).where(INVITES.c.id == identity))
            .mappings()
            .one()
        )
        assert row["reported_by"] == str(manager.user_id)
        assert row["consent_source"] == "instagram"
        from tests.postgres_financial.test_creator_social import seed_profile

        creator = seed_profile(db, stable_id=uuid4().hex)
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == creator)
            .values(status="active", telegram="direct_creator")
        )
        db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == creator)
            .values(instagram_url="https://instagram.com/from_direct")
        )
    clock.at += timedelta(minutes=1)
    with pytest.raises(ValueError, match="use_personal_link"):
        await service.selection.respond(order_id, creator)
    accepted = await service.accept(identity, creator)
    assert accepted.paid_item_id == item
    assert await service.claim_manager_notice(identity) == (
        int(manager.telegram_id),
        order_id,
        1,
    )
    assert await service.claim_manager_notice(identity) is None
    with pytest.raises(ValueError, match="unavailable"):
        await service.reported_contact_text(client, identity)
    assert await service.delivery.run_once() == 0
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_register_known_manager_with_existing_draft(intake_env):
    env = intake_env
    uid = env["admin"].user_id
    service = ManagerApplications(env["container"].transaction_manager, None)
    await service.open(uid)
    await service.answer(uid, "name", "Менеджер")
    with Session(env["pg"]) as db, db.begin():
        db.get(UserModel, uid).telegram = "known_manager"
        _review(db, "register", "@known_manager", "")
    row = await service.open(uid)
    assert row["registered_by_admin"]
    assert row["answers"]["name"] == "Менеджер"
    assert row["instagram_verified_at"] is None
    assert await service.approved(uid)
