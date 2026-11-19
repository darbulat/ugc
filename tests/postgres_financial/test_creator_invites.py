"""Manual contact stays in the card and shares the paid allocation proof."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tests.helpers.fakes import (
    FakeCallback,
    FakeMessage,
    FakeMessengerClient,
    FakeUser,
)
from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine,
    intake_env,
    paid_order,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.bot.telegram.handlers.creator_invites import (
    accept_creator_invite,
    show_invite,
)
from ugc_bot.bot.telegram.handlers.order_summary import (
    order_summary_callback,
    render_card,
)
from ugc_bot.container.creator_invite_factory import build_creator_invites
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ManagerOrderModel,
    OrderItemModel,
    UserModel,
)
from ugc_bot.infrastructure.db.order_review_models import OWNERS
from ugc_bot.infrastructure.db.repositories.creator_invites import create_invite
from ugc_bot.infrastructure.db.selection_delivery_models import ACCEPTED
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)

__all__ = ["financial_pg_engine", "intake_env"]


@pytest.mark.asyncio
async def test_contact_via_scoped_invite_after_deadline(intake_env):
    from tests.postgres_financial.test_creator_social import seed_profile

    env = intake_env
    summary, order_id, _, principal, bot = await paid_order(
        env, interested_creators=0
    )
    engine, clock = env["pg"], env["clock"]
    manager = env["admin"].user_id
    service = build_creator_invites(summary.transactions)
    service.clock = service.selection.clock = service.delivery.clock = clock
    with Session(engine) as db, db.begin():
        positions = db.scalars(
            select(OrderItemModel)
            .where(OrderItemModel.order_id == order_id)
            .order_by(OrderItemModel.ordinal)
        ).all()
        first, second = positions[0].paid_item_id, positions[1].paid_item_id
        deadline = positions[0].selection_due_at
        db.add(
            ManagerOrderModel(
                order_id=order_id, user_id=manager, created_at=clock.now()
            )
        )
        db.flush()
        external = create_invite(
            db, order_id, first, manager, "@from_instagram", clock.now()
        )
        assert (
            create_invite(
                db, order_id, first, manager, "@from_instagram", clock.now()
            )
            == external
        )
        known_creator = seed_profile(db, stable_id=uuid4().hex)
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == known_creator)
            .values(status="active")
        )
        db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == known_creator)
            .values(instagram_url="https://www.instagram.com/from_database")
        )
        known = create_invite(
            db,
            order_id,
            second,
            manager,
            "https://instagram.com/from_database",
            clock.now(),
        )
    clock.at = deadline + timedelta(minutes=1)
    telegram_user = FakeUser(123, "from_instagram", "Креатор")
    message = FakeMessage(user=telegram_user)
    roles = SimpleNamespace(get_user=AsyncMock(return_value=None))
    await show_invite(message, roles, service, "oi_" + external.hex)
    text, keyboard = message.answers[-1]
    action = FakeCallback(
        keyboard.inline_keyboard[0][0].callback_data, telegram_user, message
    )
    assert "from_instagram" in text
    assert "разрешаю" in keyboard.inline_keyboard[0][0].text
    with pytest.raises(ValueError, match="creator_invite_unavailable"):
        await service.preview(known, principal.user_id)
    with pytest.raises(ValueError, match="creator_invite_instagram_mismatch"):
        await service.accept(external, known_creator)
    with Session(engine) as db, db.begin():
        external_creator = seed_profile(db, stable_id=uuid4().hex)
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == external_creator)
            .values(status="active")
        )
        db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == external_creator)
            .values(
                instagram_url="https://www.instagram.com/from_instagram",
                confirmed=False,
            )
        )
    roles.get_user.return_value = SimpleNamespace(user_id=external_creator)
    await accept_creator_invite(action, roles, service)
    assert "подтвердите Instagram" in action.answers[-1]
    before = await summary.view(principal, order_id)
    assert before["positions"][0]["assignment_id"] is None
    with Session(engine) as db, db.begin():
        db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == external_creator)
            .values(confirmed=True)
        )
    await accept_creator_invite(action, roles, service)
    assert action.answers[-1] == "Участие подтверждено."
    interest = await service.accept(external, external_creator)
    replay = await service.accept(external, external_creator)
    assert interest == replay and interest.paid_item_id == first
    assert (await service.accept(known, known_creator)).paid_item_id == second
    with Session(engine) as db:
        assert (
            db.scalar(
                select(INVITES.c.interest_id).where(INVITES.c.id == external)
            )
            == interest.interest_id
        )
        assert (
            db.scalar(
                select(OWNERS.c.manager_id).where(
                    OWNERS.c.paid_item_id == first
                )
            )
            == manager
        )
        assert (
            db.scalar(
                select(ACCEPTED.c.delivery_id).where(
                    ACCEPTED.c.paid_item_id == first
                )
            )
            is None
        )
    assert await service.delivery.run_once() == 0
    bot.send_message.assert_not_awaited()
    data = await summary.view(principal, order_id)
    _, card = render_card(summary, data)
    contact_button = next(
        button
        for row in card.rows
        for button in row
        if button.text == "Контакт №1"
    )
    outsider = AuthenticatedMessengerPrincipal(
        env["admin"].user_id, "telegram", env["admin"].telegram_id
    )
    transport = SimpleNamespace(
        send=AsyncMock(side_effect=lambda attempt: fake_receipt(attempt))
    )
    with pytest.raises(ValueError, match="creator_invite_contact_unavailable"):
        await service.card_contact(outsider, interest.assignment_id, transport)
    transport.send.assert_not_awaited()
    customer = FakeUser(int(principal.external_id), "customer", "Заказчик")
    customer_card = FakeMessage(user=customer, message_id=1234)
    async with summary.transactions.transaction() as db:
        assert await summary.summaries.claim_message(
            order_id, principal.user_id, clock.now(), session=db
        )
        await summary.record_card_delivery(
            order_id, principal.user_id, "1234", session=db
        )
    roles.get_user.return_value = SimpleNamespace(user_id=principal.user_id)
    messenger = FakeMessengerClient()
    for _ in range(2):
        await order_summary_callback(
            FakeCallback(contact_button.callback_data, customer, customer_card),
            roles,
            summary,
            service,
            messenger,
            TelegramEventAdapter(),
        )
    assert not messenger.sent_text
    assert len(messenger.edited_text) == 2
    assert "from_instagram" in messenger.edited_text[-1]["text"]
    with Session(engine) as db:
        assert (
            len(
                db.scalars(
                    select(ACCEPTED).where(ACCEPTED.c.paid_item_id == first)
                ).all()
            )
            == 1
        )


def fake_receipt(attempt):
    from ugc_bot.application.notice_delivery_ports import DeliveryReceipt

    return DeliveryReceipt(attempt.channel, f"test-card:{attempt.interest_id}")


@pytest.mark.asyncio
async def test_admin_creates_invite_from_order(intake_env, monkeypatch):
    from re import search

    from tests.postgres_financial.test_creator_social import seed_profile
    from ugc_bot.admin.app import create_admin_app

    env = intake_env
    _, order_id, _, _, _ = await paid_order(env, interested_creators=0)
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
        creator = seed_profile(db, stable_id=uuid4().hex)
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == creator)
            .values(telegram_id="12341234", telegram="known_contact")
        )
        db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == creator)
            .values(instagram_url="https://instagram.com/known_contact")
        )
    send = AsyncMock(return_value="sent")
    monkeypatch.setattr("ugc_bot.admin.creator_invites.dispatch_invite", send)

    async def customer_receipt(config, service, identity):
        from ugc_bot.infrastructure.db.invite_handoff_models import NOTICES

        with Session(env["pg"]) as db, db.begin():
            db.execute(
                NOTICES.insert().values(
                    invite_id=identity,
                    kind="customer",
                    state="sent",
                )
            )
        return "sent"

    send_customer = AsyncMock(side_effect=customer_receipt)
    monkeypatch.setattr(
        "ugc_bot.admin.creator_invites.dispatch_customer_contact", send_customer
    )
    path = f"/admin/orders/{order_id}/creator-invites"
    with TestClient(create_admin_app()) as client:
        assert client.get(path, follow_redirects=False).is_redirect
        assert client.post(
            "/admin/login",
            data={"username": "test_admin", "password": "test_pass"},
            follow_redirects=False,
        ).is_redirect
        page = client.get(path)
        assert page.status_code == 200
        token = search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert "Без выбора — заказчик" in page.text
        assert 'id="invite-consent"' in page.text
        assert "<summary>Креатор уже согласился" not in page.text
        assert 'value="send_customer"' in page.text
        assert 'value="create">Создать ссылку' in page.text
        position = search(
            r'<option value="([a-f0-9-]{36})"[^>]*>№1</option>', page.text
        )
        assert token and position
        form = {"instagram": "@external_creator", "item_id": position[1]}
        assert client.post(path, data=form).status_code == 403
        page = client.post(path, data={**form, "csrf_token": token[1]})
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
        assert search(
            r"https://t.me/example_test_bot[?]start=oi_[a-f0-9]{32}", page.text
        )
        assert "Ждём подтверждения" in page.text
        assert "Первая свободная · №2" in page.text
        assert ">№1</option>" not in page.text
        known = {
            "instagram": "@known_contact",
            "telegram": "@known_contact",
            "csrf_token": token[1],
        }
        checked = client.post(path, data={**known, "operation": "preview"})
        assert "бот доступен" in checked.text
        send.assert_not_awaited()
        invalid = client.post(
            path,
            data={**known, "operation": "send_customer", "record_consent": "1"},
        )
        assert invalid.status_code == 422
        assert "Укажите, где получено согласие креатора." in invalid.text
        assert 'value="@known_contact"' in invalid.text
        assert "Проверьте выбранную позицию" not in invalid.text
        send_customer.assert_not_awaited()
        missing = client.post(
            path, data={**known, "operation": "send_customer"}
        )
        assert missing.status_code == 422
        assert "Подтвердите согласие креатора" in missing.text
        sent = client.post(path, data={**known, "operation": "send"})
        assert "Приглашение отправлено в Telegram." in sent.text
        assert "Ссылка готова" not in sent.text
        send.assert_awaited_once()
        manual = client.post(
            path,
            data={
                **known,
                "operation": "send",
                "record_consent": "1",
                "consent_source": "telegram",
            },
        )
        assert "Ссылка готова" in manual.text
        send.assert_awaited_once()
        sent_customer = client.post(
            path,
            data={
                **known,
                "operation": "send_customer",
                "record_consent": "1",
                "consent_source": "telegram",
            },
        )
        assert sent_customer.status_code == 200
        assert [response.status_code for response in sent_customer.history] == [
            303
        ]
        assert "Контакт отправлен заказчице в Telegram" in sent_customer.text
        assert "Позиция №2 из 10" in sent_customer.text
        assert "Добавить следующего креатора · №3" in sent_customer.text
        assert 'id="invite-creator-form"' not in sent_customer.text
        refreshed = client.get(str(sent_customer.url))
        assert "Контакт отправлен заказчице в Telegram" in refreshed.text
        next_page = client.get(path)
        assert 'value="@known_contact"' not in next_page.text
        assert (
            'id="invite-consent" type="checkbox" '
            'name="record_consent" value="1">' in next_page.text
        )
        assert "Первая свободная · №3" in next_page.text
        forged = client.get(path, params={"sent": str(uuid4())})
        assert 'id="invite-result"' not in forged.text
        send_customer.assert_awaited_once()
        send.assert_awaited_once()
