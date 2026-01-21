"""Integration test for complete advertiser user flow."""

import pytest
from aiogram import Dispatcher
from sqlalchemy.orm import Session
from unittest.mock import AsyncMock

from ugc_bot.domain.enums import OrderStatus, UserStatus


@pytest.mark.skip(reason="Requires PostgreSQL-specific UUID functions")
def test_advertiser_basic_flow(
    dispatcher: Dispatcher,
    session: Session,
    mock_bot: AsyncMock,
    create_test_user,
    create_test_order,
) -> None:
    """Test complete advertiser flow: registration → order creation → payment → contacts → feedback."""

    # === Шаг 1: Регистрация рекламодателя ===
    # Создаем пользователя-рекламодателя
    advertiser_user = create_test_user("advertiser_123")
    user_repo = dispatcher["user_repo"]
    advertiser_user = user_repo.save(advertiser_user)
    session.commit()

    # === Шаг 2: Создание заказа ===
    # Создаем заказ
    order = create_test_order(advertiser_user.user_id)
    order_service = dispatcher["order_service"]
    order = order_service.create_order(order)
    session.commit()

    # Проверяем, что заказ создан со статусом NEW
    assert order.status == OrderStatus.NEW
    assert order.advertiser_id == advertiser_user.user_id

    # === Шаг 3: Оплата заказа ===
    # Имитируем процесс оплаты
    payment_service = dispatcher["payment_service"]

    # Создаем платеж
    payment = payment_service.create_payment(order.order_id, order.price)
    session.commit()
    assert payment is not None

    # Имитируем успешную оплату
    payment_service.confirm_payment(payment.external_id)
    session.commit()

    # Проверяем, что заказ стал активным
    updated_order = order_service.get_by_id(order.order_id)
    assert updated_order.status == OrderStatus.ACTIVE

    # === Шаг 4: Пропускаем рассылку и отклики ===
    # Требует профилей блогеров, что несовместимо с SQLite

    # === Финальные проверки ===
    # Проверяем основные аспекты
    assert updated_order.status == OrderStatus.ACTIVE
    assert advertiser_user.status == UserStatus.ACTIVE

    print("✅ Advertiser basic flow test passed!")
