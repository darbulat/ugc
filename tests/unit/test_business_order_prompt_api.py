"""Only active recipients can read the contact-scrubbed order projection."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from time import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.e2e.miniapp_helpers import generate_init_data
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import AdvertiserProfile, Order, Payment, User
from ugc_bot.domain.enums import (
    BloggerGender,
    MessengerType,
    OrderStatus,
    OrderType,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.miniapp.business_order_prompt_api import (
    SqlAlchemyOrderNoticeDetailsRepository,
    router,
)

TOKEN = "test-bot"
ENDPOINT = "/orders/gpt-copy"


@pytest.fixture
def export(monkeypatch):
    now = datetime.now(timezone.utc)
    actor = User(
        user_id=uuid4(),
        telegram_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
        admin=True,
    )
    client = replace(
        actor,
        user_id=uuid4(),
        telegram_id="102030405",
        telegram="brand_operator",
        username="Мария Примерова",
        admin=False,
    )
    order = Order(
        order_id=uuid4(),
        advertiser_id=client.user_id,
        order_type=OrderType.UGC_PLUS_PLACEMENT,
        product_link="https://example.com/private-product",
        brief_link="https://example.com/private-brief",
        offer_text=(
            "Снять обзор приложения. Мария Примерова, команда Бренд Тест.\n\n"
            "Показать экран и живую реакцию. "
            "Контакты: t.me/brand_operator, @brand_operator, "
            "+7 (912) 345-67-89, 8.921.123.45.67, "
            "telegram:102030405, max:43567, brand@example.com. "
            "Запасной канал — вацап 89001112233, письмо через "
            "mailto:a@example.ru, Телеграм: no_at_handle. "
            "Свободный контакт ExampleContact."
        ),
        barter_description="Продукт с доставкой. Связь через wa.me/79123456789",
        price=1250.5,
        bloggers_needed=10,
        status=OrderStatus.PENDING_MODERATION,
        created_at=now,
        geography="любом",
        deadlines="Показать черновик к 22.11.2026 19:17",
        content_usage="Соцсети и реклама бренда",
        min_followers=1_234_567_890,
        required_blogger_gender=BloggerGender.FEMALE,
        financial_version="version",
    )
    profile = AdvertiserProfile(
        user_id=client.user_id,
        phone="+79123456789",
        brand="Бренд Тест",
        site_link="https://example.com/client",
    )
    payment = Payment(
        payment_id=uuid4(),
        order_id=order.order_id,
        provider="test",
        status=PaymentStatus.PAID,
        amount=7400,
        currency="RUB",
        external_id="private-payment-reference",
        created_at=now,
    )
    quote = AsyncMock(
        return_value={
            "contact_reference": "ExampleContact",
            "accompaniment_count": 2,
            "position_count": 10,
            "selection_due_display": "22.11.2026 16:17:55 UTC",
            "selection_base_minor": 500000,
            "accompaniment_minor": 240000,
            "total_minor": 740000,
        }
    )
    monkeypatch.setattr(SqlAlchemyOrderNoticeDetailsRepository, "load", quote)
    repos = {
        "user_repo": AsyncMock(),
        "order_repo": AsyncMock(),
        "advertiser_repo": AsyncMock(),
        "payment_repo": AsyncMock(),
        "order_intake_repo": AsyncMock(),
    }
    repos["user_repo"].get_by_id.side_effect = lambda uid, **_: (
        client if uid == client.user_id else actor
    )
    repos["order_repo"].get_by_id.return_value = order
    repos["advertiser_repo"].get_by_user_id.return_value = profile
    repos["payment_repo"].get_by_order.return_value = payment
    repos["order_intake_repo"].target_platforms_for_order.return_value = (
        "instagram",
        "tiktok",
    )
    roles = AsyncMock()
    roles.get_user.side_effect = lambda uid, _: replace(actor, telegram_id=uid)

    @asynccontextmanager
    async def transaction():
        yield object()

    app = FastAPI()
    app.include_router(router)
    app.state.config = AppConfig.model_validate(
        {"BOT_TOKEN": TOKEN, "BUSINESS_ORDER_TELEGRAM_RECIPIENTS": ["123"]}
    )
    app.state.dispatcher = {
        "user_role_service": roles,
        "container": SimpleNamespace(
            transaction_manager=SimpleNamespace(transaction=transaction),
            build_repos=lambda: repos,
        ),
    }
    return SimpleNamespace(
        app=app, actor=actor, quote=quote, order=order, repos=repos
    )


def _post(export, *, uid=123, signed=None, route=ENDPOINT, **extra):
    return TestClient(export.app).post(
        route,
        json={
            "init_data": signed
            if signed is not None
            else generate_init_data(TOKEN, uid, "admin"),
            "order_id": str(export.order.order_id),
            **extra,
        },
    )


def test_copy_prompt_keeps_full_brief_without_contacts(export):
    export.repos["order_repo"].get_by_id.return_value = replace(
        export.order,
        offer_text=export.order.offer_text
        + "\n\n"
        + "Детали сценария. " * 165
        + "Последняя деталь.",
    )
    response = _post(export)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    prompt = response.json()["prompt"]
    assert "первое сообщение заказчику" in prompt
    assert "Зацепись за конкретную деталь" in prompt
    assert "Один важный вопрос".lower() in prompt
    assert "UGC + размещение" in prompt
    assert "1250.5 RUB" in prompt
    assert "География — Любой город" in prompt
    assert "Instagram, TikTok" in prompt
    assert "1234567890" in prompt
    assert "женщины" in prompt
    assert "Продукт с доставкой" in prompt
    assert "22.11.2026 19:17" in prompt
    assert "22.11.2026 16:17:55 UTC" in prompt
    assert "подтверждена" in prompt
    assert "7400 RUB" in prompt
    assert "для 2 из 10" in prompt
    assert "Показать экран и живую реакцию" in prompt
    assert "Последняя деталь." in prompt
    for private in (
        "Мария Примерова",
        "Бренд Тест",
        "brand_operator",
        "private-product",
        "private-brief",
        "102030405",
        "43567",
        "345-67-89",
        "921.123",
        "89001112233",
        "brand@example.com",
        "a@example.ru",
        "ExampleContact",
        "private-payment-reference",
        "no_at_handle",
        str(export.order.order_id),
    ):
        assert private not in prompt


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("bad-signature", 401),
        ("expired", 401),
        ("other-admin", 403),
        ("revoked", 403),
        ("blocked", 403),
        ("remapped", 403),
        ("wrong-network", 403),
        ("max", 422),
        ("query", 422),
        ("missing-runtime", 503),
    ],
)
def test_copy_prompt_checks_current_access_before_reading_order(
    export, case, code
):
    opts = {}
    if case == "bad-signature":
        opts["signed"] = generate_init_data("wrong-bot", 123, "admin")
    elif case == "expired":
        opts["signed"] = generate_init_data(
            TOKEN, 123, "admin", auth_date=int(time()) - 86401
        )
    elif case == "other-admin":
        opts["uid"] = 456
    elif case == "revoked":
        export.repos["user_repo"].get_by_id.side_effect = None
        export.repos["user_repo"].get_by_id.return_value = replace(
            export.actor, admin=False
        )
    elif case == "blocked":
        export.repos["user_repo"].get_by_id.side_effect = None
        export.repos["user_repo"].get_by_id.return_value = replace(
            export.actor, status=UserStatus.BLOCKED
        )
    elif case == "remapped":
        export.repos["user_repo"].get_by_id.side_effect = None
        export.repos["user_repo"].get_by_id.return_value = replace(
            export.actor, telegram_id="999"
        )
    elif case == "wrong-network":
        export.repos["user_repo"].get_by_id.side_effect = None
        export.repos["user_repo"].get_by_id.return_value = replace(
            export.actor, messenger_type=MessengerType.MAX
        )
    elif case == "max":
        opts["platform"] = "max"
    elif case == "query":
        opts["route"] = ENDPOINT + "?init_data=unexpected"
    else:
        export.app.state.dispatcher.pop("container")
    response = _post(export, **opts)
    assert response.status_code == code
    assert response.headers["cache-control"] == "no-store"
    export.repos["order_repo"].get_by_id.assert_not_awaited()


@pytest.mark.parametrize("deleted", [False, True])
def test_copy_prompt_order_unavailable(export, deleted):
    export.repos["order_repo"].get_by_id.return_value = (
        replace(export.order, status=OrderStatus.DELETED) if deleted else None
    )
    assert _post(export).status_code == 404
    export.quote.assert_not_awaited()


@pytest.mark.parametrize("complimentary", [False, True])
def test_copy_prompt_legacy_without_payment_or_brief(export, complimentary):
    export.quote.return_value = None
    export.repos["payment_repo"].get_by_order.return_value = None
    export.repos["advertiser_repo"].get_by_user_id.return_value = None
    export.repos["user_repo"].get_by_id.side_effect = lambda uid, **_: (
        export.actor if uid == export.actor.user_id else None
    )
    export.repos["order_repo"].get_by_id.return_value = replace(
        export.order,
        financial_version=None,
        offer_text="",
        complimentary=complimentary,
    )
    response = _post(export)
    assert response.status_code == 200
    status = (
        "по согласованию без оплаты"
        if complimentary
        else "подтверждение оплаты отсутствует"
    )
    assert f"Оплата — {status}" in response.json()["prompt"]
    assert "Описание задачи" not in response.json()["prompt"]
    export.repos[
        "order_intake_repo"
    ].target_platforms_for_order.assert_not_awaited()
