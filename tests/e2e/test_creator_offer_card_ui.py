"""Creator-card moderation through the actual order editor."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.e2e.test_admin_ui import _login
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.db import manager_application_models  # noqa: F401
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    OrderModel,
    UserModel,
)


@pytest.mark.e2e
@pytest.mark.timeout(45)
@pytest.mark.parametrize("existing_card", [None, {}])
@pytest.mark.parametrize("communication_role", [None, "client", "manager"])
def test_public_card_saves_as_draft_and_rejects_private_links(
    admin_server, page, test_database, existing_card, communication_role
):
    if not test_database:
        pytest.skip("Requires the isolated local browser database")
    engine = create_engine(test_database)
    now = datetime.now(timezone.utc)
    client_id, order_id = uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            UserModel(
                user_id=client_id,
                username="Тестовый заказчик карточки",
                messenger_type=MessengerType.TELEGRAM,
                status=UserStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            AdvertiserProfileModel(
                user_id=client_id,
                contact="test",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            OrderModel(
                order_id=order_id,
                advertiser_id=client_id,
                status=OrderStatus.NEW,
                offer_text="Private brand and full specifications",
                product_link="https://private.example.test/product",
                price=3000,
                bloggers_needed=10,
                creator_offer_card=existing_card,
                created_at=now,
                updated_at=now,
            )
        )
    values = {
        "sender_name": "UseMyContent",
        "title": "Тестовая съёмка",
        "task": "Покажи один день с приложением",
        "deadline": "7 дней после согласования",
        "usage": "Соцсети заказчика",
        "brief": "Вертикальный ролик с записью экрана",
        "contact": "@synthetic_client",
    }
    try:
        _login(page, admin_server)
        page.goto(f"{admin_server}/admin/order-model/edit/{order_id}")
        if existing_card is None:
            page.get_by_label(
                "Использовать новую карточку для этого черновика"
            ).check()
        expect(page.locator("body")).not_to_contain_text("Набор завершён")
        for name, value in values.items():
            page.locator(f'[name="creator_card_{name}"]').fill(value)
        if communication_role:
            choice = page.get_by_label("Кто общается с креатором")
            choice.select_option("client")
            page.get_by_label("Telegram заказчика", exact=True).fill(
                "@client_account"
            )
            choice.select_option("manager")
            page.get_by_label("Telegram менеджера", exact=True).fill(
                "@manager_account"
            )
            choice.select_option(communication_role)
            values.update(
                communication_role=communication_role,
                client_contact="@client_account",
                manager_contact="@manager_account",
                contact=f"@{communication_role}_account",
            )
        page.get_by_role(
            "button", name="Сохранить и остаться", exact=True
        ).click()
        expect(page.locator("#creator-card-title")).to_have_value(
            values["title"]
        )
        page.reload()
        for name, value in values.items():
            if name == "contact" and communication_role:
                # The compatibility value is resolved by the server on save.
                continue
            expect(page.locator(f'[name="creator_card_{name}"]')).to_have_value(
                value
            )
        if communication_role:
            selected = page.locator(
                f'[name="creator_card_{communication_role}_contact"]'
            )
            expect(selected).to_be_visible()
            other = "manager" if communication_role == "client" else "client"
            expect(
                page.locator(f'[name="creator_card_{other}_contact"]')
            ).to_be_hidden()
        with Session(engine) as session:
            order = session.get(OrderModel, order_id)
            assert order.status == OrderStatus.NEW
            assert order.creator_offer_card == values
            assert order.product_link == "https://private.example.test/product"
            assert not order.creator_offer_card.get("photo")
        page.locator('[name="creator_card_task"]').fill(
            "Посмотрите https://private.example.test/product"
        )
        page.get_by_role(
            "button", name="Сохранить и остаться", exact=True
        ).click()
        expect(
            page.get_by_text(
                "Уберите ссылки и контакты из публичной карточки.",
                exact=False,
            )
        ).to_be_visible()
        with Session(engine) as session:
            order = session.get(OrderModel, order_id)
            assert order.creator_offer_card == values
            assert order.status == OrderStatus.NEW
    finally:
        engine.dispose()


@pytest.mark.e2e
@pytest.mark.timeout(45)
def test_admin_shows_reserve_and_finished_intake(
    admin_server, page, test_database
):
    if not test_database:
        pytest.skip("Requires the isolated local browser database")
    engine = create_engine(test_database)
    client_id, order_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    with Session(engine) as db, db.begin():
        db.add(
            UserModel(
                user_id=client_id,
                username="Reserve test client",
                created_at=now,
                updated_at=now,
                messenger_type=MessengerType.TELEGRAM,
                status=UserStatus.ACTIVE,
            )
        )
        db.flush()
        db.add(
            OrderModel(
                order_id=order_id,
                advertiser_id=client_id,
                status=OrderStatus.ACTIVE,
                offer_text="Reserve UI test",
                created_at=now,
                updated_at=now,
                product_link="https://example.test",
                price=500,
                bloggers_needed=1,
                offer_reserve_until=now + timedelta(hours=72),
            )
        )
    try:
        _login(page, admin_server)
        page.goto(f"{admin_server}/admin/orders/{order_id}")
        activity = page.locator("#order-offer-activity")
        expect(activity).to_contain_text("Основной состав набран")
        expect(activity).to_contain_text("Участие не гарантировано")
        with Session(engine) as db, db.begin():
            db.get(OrderModel, order_id).offer_reserve_until = now
        page.reload()
        expect(page.locator("#order-offer-activity")).to_contain_text(
            "Набор завершён"
        )
    finally:
        with Session(engine) as db, db.begin():
            db.delete(db.get(OrderModel, order_id))
            db.delete(db.get(UserModel, client_id))
        engine.dispose()
