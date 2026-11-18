"""Verify the saved campaign audience and the editor's live preview."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ugc_bot.admin import app as admin_app
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    RejectionReason,
    UserStatus,
)
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.dispatch_control import CLAIMS, CONTROLS
from ugc_bot.infrastructure.db.models import (
    OfferDispatchModel,
    OrderModel,
    UserModel,
)


def test_admin_offer_activity_tracks_recipients_and_legacy_orders(
    monkeypatch, tmp_path
):
    db_url = f"sqlite:///{tmp_path / 'offer_activity.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("USE_REDIS_STORAGE", "false")
    engine = create_engine(db_url)
    tables = [
        "users",
        "orders",
        "offer_dispatches",
        "offer_channel_attribution",
        "order_creator_invites",
        "order_dispatch_controls",
        "order_dispatch_claims",
        "creator_social_accounts",
    ]
    Base.metadata.create_all(
        engine, tables=[Base.metadata.tables[t] for t in tables]
    )
    order, customer, counteroffer, invited, undeliverable = (
        uuid4() for _ in range(5)
    )
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        db.add_all(
            UserModel(
                user_id=user_id,
                username=name,
                messenger_type=MessengerType.TELEGRAM,
                status=UserStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            for user_id, name in (
                (customer, "Заказчик"),
                (counteroffer, "<Креатор>"),
                (invited, "Отклик по личной ссылке"),
                (undeliverable, "Ошибка доставки"),
            )
        )
        db.add(
            OrderModel(
                order_id=order,
                advertiser_id=customer,
                status=OrderStatus.ACTIVE,
                offer_text="Тест офферов",
                product_link="https://example.test",
                price=1000,
                bloggers_needed=10,
                created_at=now,
                updated_at=now,
            )
        )
        db.add_all(
            [
                OfferDispatchModel(
                    order_id=order,
                    blogger_id=counteroffer,
                    created_at=now,
                    accepted=False,
                    in_offer=False,
                    rejection_reason=RejectionReason.LOW_PRICE,
                    desired_price=3000,
                ),
                OfferDispatchModel(
                    order_id=order,
                    blogger_id=invited,
                    created_at=now,
                    accepted=True,
                    in_offer=True,
                ),
            ]
        )
        db.flush()
        db.execute(
            insert(INVITES).values(
                id=uuid4(),
                order_id=order,
                item_id=uuid4(),
                instagram="creator",
                expires_at=now + timedelta(hours=1),
                consented_at=now,
                creator_id=invited,
                interest_id=uuid4(),
            )
        )

    client = TestClient(admin_app.create_admin_app())
    path = f"/admin/orders/{order}/offer-activity"
    assert client.get(path).status_code == 401
    client.post(
        "/admin/login",
        data={"username": "test_admin", "password": "test_pass"},
        follow_redirects=False,
    )
    assert (
        client.get(f"/admin/orders/{uuid4()}/offer-activity").status_code == 404
    )
    old = client.get(path)
    assert old.status_code == 200
    assert old.headers["Cache-Control"] == "private, no-store"
    assert "<strong>—</strong>" in old.text
    assert "&lt;Креатор&gt;" in old.text and "3 000 ₽" in old.text

    with engine.begin() as db:
        db.execute(
            insert(CONTROLS).values(
                order_id=order,
                run=1,
                paused=False,
                audience_ready=False,
            )
        )
    assert "Готовим выборку для рассылки" in client.get(path).text
    with engine.begin() as db:
        db.execute(update(CONTROLS).values(audience_ready=True))
    assert "Нет получателей" in client.get(path).text
    with engine.begin() as db:
        db.execute(
            insert(CLAIMS),
            [
                {
                    "order_id": order,
                    "blogger_id": uid,
                    "run": 1,
                    "rejected": uid == undeliverable,
                }
                for uid in (counteroffer, invited, undeliverable)
            ],
        )
    activity = client.get(path).text
    assert "<strong>1 из 3</strong>" in activity
    assert "Рассылка завершена" in activity
    assert "Приняли личное приглашение · 1" in activity

    with engine.begin() as db:
        db.execute(
            update(CLAIMS)
            .where(CLAIMS.c.blogger_id == undeliverable)
            .values(rejected=False)
        )
    assert "Авторов без результата отправки — 1" in client.get(path).text
    with engine.begin() as db:
        db.execute(update(CONTROLS).values(paused=True))
    assert "Рассылка на паузе" in client.get(path).text
    with engine.begin() as db:
        db.execute(update(OrderModel).values(status=OrderStatus.CLOSED))
    assert "Рассылка остановлена" in client.get(path).text
    engine.dispose()


def test_editor_preview_uses_unsaved_filters_without_changing_order(
    monkeypatch,
):
    monkeypatch.setenv("USE_REDIS_STORAGE", "false")
    order = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.test",
        offer_text="Тест фильтров",
        barter_description=None,
        price=1000,
        bloggers_needed=10,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(UTC),
        geography="Россия",
    )
    session = object()

    @asynccontextmanager
    async def transaction():
        yield session

    dispatcher = SimpleNamespace(
        order_repo=SimpleNamespace(get_by_id=AsyncMock(return_value=order)),
        intake_repository=SimpleNamespace(
            exact_city_for_order=AsyncMock(return_value="Казань")
        ),
        count_order_candidates=AsyncMock(return_value=70),
    )
    geocode = AsyncMock(return_value="MULTIPOLYGON EMPTY")
    container = SimpleNamespace(
        transaction_manager=SimpleNamespace(transaction=transaction),
        build_offer_dispatch_service=lambda: dispatcher,
        build_geocoder=lambda: SimpleNamespace(
            get_multipolygon_wkt_for_queries=geocode
        ),
    )
    client = TestClient(admin_app.create_admin_app())
    monkeypatch.setattr(admin_app, "_get_admin_container", lambda: container)
    client.post(
        "/admin/login",
        data={"username": "test_admin", "password": "test_pass"},
        follow_redirects=False,
    )
    path = f"/admin/api/orders/{order.order_id}/audience"
    response = client.get(
        path, params={"geography": "Казань", "min_followers": 2000}
    )
    assert response.json() == {"count": 70}
    assert response.headers["Cache-Control"] == "no-store"
    dispatcher.count_order_candidates.assert_awaited_once_with(
        replace(
            order,
            geography="Казань",
            min_followers=2000,
            location_geometry="MULTIPOLYGON EMPTY",
        ),
        session=session,
    )
    assert client.get(path, params={"geography": "любой"}).status_code == 422
    assert (
        client.get(path, params={"min_age": 41, "max_age": 20}).status_code
        == 422
    )

    priced_order = replace(order, financial_version="test", geography="Казань")
    dispatcher.order_repo.get_by_id.return_value = priced_order
    assert client.get(path, params={"geography": "Россия"}).status_code == 422
    same_city = client.get(path, params={"geography": "Казань", "price": 5000})
    assert same_city.json() == {"count": 70}
    dispatcher.count_order_candidates.assert_awaited_with(
        priced_order, session=session
    )
    geocode.assert_awaited_once()

    dispatcher.order_repo.get_by_id.return_value = order
    geocode.return_value = None
    assert client.get(path, params={"geography": "Казань"}).status_code == 422
    dispatcher.count_order_candidates.side_effect = TimeoutError
    assert client.get(path).status_code == 503
    dispatcher.count_order_candidates.side_effect = SQLAlchemyError
    assert client.get(path).status_code == 503
    dispatcher.order_repo.get_by_id.return_value = None
    assert client.get(path).status_code == 404
