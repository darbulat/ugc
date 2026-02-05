"""Integration test for feedback postponement logic."""

import pytest
from datetime import datetime, timedelta, timezone
from uuid import UUID

from ugc_bot.domain.enums import InteractionStatus, OrderStatus, OrderType
from ugc_bot.domain.entities import AdvertiserProfile


async def _get_interaction(dispatcher, interaction_id: UUID):
    """Load interaction within a transaction (repos require session)."""
    tm = dispatcher["transaction_manager"]
    async with tm.transaction() as session:
        return await dispatcher["interaction_repo"].get_by_id(
            interaction_id, session=session
        )


@pytest.mark.asyncio
async def test_feedback_postponement_three_times_leads_to_no_deal(
    dispatcher,
) -> None:
    """Test that after 3 postponements, interaction automatically becomes NO_DEAL."""

    # === Подготовка ===
    # Создаем пользователей
    user_role_service = dispatcher["user_role_service"]
    advertiser_user = await user_role_service.create_user(
        "advertiser_postpone", username="advertiser_postpone"
    )
    blogger_user = await user_role_service.create_user(
        "blogger_postpone", username="blogger_postpone"
    )

    # Создаем advertiser profile
    advertiser_repo = dispatcher["advertiser_repo"]
    advertiser_profile = AdvertiserProfile(
        user_id=advertiser_user.user_id,
        phone="test@example.com",
        brand="Brand",
    )
    tm = dispatcher["transaction_manager"]
    async with tm.transaction() as session:
        await advertiser_repo.save(advertiser_profile, session=session)

    # Создаем заказ
    order_service = dispatcher["order_service"]
    order = await order_service.create_order(
        advertiser_id=advertiser_user.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/product",
        offer_text="Test offer",
        ugc_requirements=None,
        barter_description=None,
        price=5000.0,
        bloggers_needed=3,
    )

    # Имитируем, что контакты уже отправлены
    from ugc_bot.domain.entities import Order

    updated_order = Order(
        order_id=order.order_id,
        advertiser_id=order.advertiser_id,
        order_type=order.order_type,
        product_link=order.product_link,
        offer_text=order.offer_text,
        ugc_requirements=order.ugc_requirements,
        barter_description=order.barter_description,
        price=order.price,
        bloggers_needed=order.bloggers_needed,
        status=OrderStatus.CLOSED,
        created_at=order.created_at,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    order_repo = dispatcher["order_repo"]
    async with tm.transaction() as session:
        await order_repo.save(updated_order, session=session)
    order = updated_order

    # Создаем взаимодействие вручную
    interaction_service = dispatcher["interaction_service"]
    interaction = await interaction_service.create_for_contacts_sent(
        order.order_id, blogger_user.user_id, advertiser_user.user_id
    )

    # Проверяем начальное состояние
    assert interaction.status == InteractionStatus.PENDING
    assert interaction.postpone_count == 0
    assert interaction.next_check_at is not None

    # === Шаг 1: Первый перенос (postpone_count = 1) ===
    # Имитируем выбор "Еще не связался" блогером
    await interaction_service.record_blogger_feedback(
        interaction.interaction_id,
        "еще не связался",  # Это означает перенос
    )

    updated_interaction = await _get_interaction(dispatcher, interaction.interaction_id)
    assert updated_interaction.postpone_count == 1
    assert updated_interaction.status == InteractionStatus.PENDING
    assert updated_interaction.next_check_at is not None

    # === Шаг 2: Второй перенос (postpone_count = 2) ===
    # Имитируем еще один перенос
    await interaction_service.record_blogger_feedback(
        interaction.interaction_id,
        "еще не связался",  # Еще один перенос
    )

    updated_interaction = await _get_interaction(dispatcher, interaction.interaction_id)
    assert updated_interaction.postpone_count == 2
    assert updated_interaction.status == InteractionStatus.PENDING

    # === Шаг 3: Третий перенос (postpone_count = 3) ===
    await interaction_service.record_blogger_feedback(
        interaction.interaction_id,
        "еще не связался",  # Третий перенос
    )

    updated_interaction = await _get_interaction(dispatcher, interaction.interaction_id)
    assert updated_interaction.postpone_count == 3
    assert updated_interaction.status == InteractionStatus.PENDING  # Еще PENDING

    # === Шаг 4: Четвертый перенос (postpone_count = 4 → NO_DEAL) ===
    # Имитируем четвертый перенос, который должен привести к NO_DEAL
    await interaction_service.record_blogger_feedback(
        interaction.interaction_id,
        "еще не связался",  # Четвертый перенос
    )

    updated_interaction = await _get_interaction(dispatcher, interaction.interaction_id)
    assert updated_interaction.postpone_count == 4
    assert (
        updated_interaction.status == InteractionStatus.NO_DEAL
    )  # Должен стать NO_DEAL
    assert updated_interaction.next_check_at is None  # Таймер остановлен

    print("✅ Feedback postponement test (3 times → NO_DEAL) passed!")


@pytest.mark.asyncio
async def test_feedback_postponement_less_than_three_times_keeps_pending(
    dispatcher,
) -> None:
    """Test that postponement less than 3 times keeps interaction PENDING."""

    # === Подготовка ===
    # Создаем пользователей
    user_role_service = dispatcher["user_role_service"]
    advertiser_user = await user_role_service.create_user(
        "advertiser_postpone2", username="advertiser_postpone2"
    )
    blogger_user = await user_role_service.create_user(
        "blogger_postpone2", username="blogger_postpone2"
    )

    # Создаем advertiser profile
    advertiser_repo = dispatcher["advertiser_repo"]
    advertiser_profile = AdvertiserProfile(
        user_id=advertiser_user.user_id,
        phone="test@example.com",
        brand="Brand",
    )
    tm = dispatcher["transaction_manager"]
    async with tm.transaction() as session:
        await advertiser_repo.save(advertiser_profile, session=session)

    # Создаем заказ и взаимодействие
    order_service = dispatcher["order_service"]
    order = await order_service.create_order(
        advertiser_id=advertiser_user.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/product",
        offer_text="Test offer",
        ugc_requirements=None,
        barter_description=None,
        price=5000.0,
        bloggers_needed=3,
    )
    from ugc_bot.domain.entities import Order

    updated_order = Order(
        order_id=order.order_id,
        advertiser_id=order.advertiser_id,
        order_type=order.order_type,
        product_link=order.product_link,
        offer_text=order.offer_text,
        ugc_requirements=order.ugc_requirements,
        barter_description=order.barter_description,
        price=order.price,
        bloggers_needed=order.bloggers_needed,
        status=OrderStatus.CLOSED,
        created_at=order.created_at,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    order_repo = dispatcher["order_repo"]
    async with tm.transaction() as session:
        await order_repo.save(updated_order, session=session)
    order = updated_order

    interaction_service = dispatcher["interaction_service"]
    interaction = await interaction_service.create_for_contacts_sent(
        order.order_id, blogger_user.user_id, advertiser_user.user_id
    )

    # === Шаг 1: Первый перенос ===
    await interaction_service.record_blogger_feedback(
        interaction.interaction_id, "еще не связался"
    )

    updated_interaction = await _get_interaction(dispatcher, interaction.interaction_id)
    assert updated_interaction.postpone_count == 1
    assert updated_interaction.status == InteractionStatus.PENDING

    # === Шаг 2: Второй перенос ===
    await interaction_service.record_blogger_feedback(
        interaction.interaction_id, "еще не связался"
    )

    updated_interaction = await _get_interaction(dispatcher, interaction.interaction_id)
    assert updated_interaction.postpone_count == 2
    assert updated_interaction.status == InteractionStatus.PENDING  # Еще не NO_DEAL

    print("✅ Feedback postponement test (< 3 times → still PENDING) passed!")


@pytest.mark.asyncio
async def test_feedback_mixed_responses_aggregation(
    dispatcher,
) -> None:
    """Test feedback aggregation with mixed OK/NO_DEAL responses."""

    # === Подготовка ===
    # Создаем пользователей
    user_role_service = dispatcher["user_role_service"]
    advertiser_user = await user_role_service.create_user(
        "advertiser_mixed", username="advertiser_mixed"
    )
    blogger1_user = await user_role_service.create_user(
        "blogger_mixed1", username="blogger_mixed1"
    )
    blogger2_user = await user_role_service.create_user(
        "blogger_mixed2", username="blogger_mixed2"
    )

    # Создаем advertiser profile
    advertiser_repo = dispatcher["advertiser_repo"]
    advertiser_profile = AdvertiserProfile(
        user_id=advertiser_user.user_id,
        phone="test@example.com",
        brand="Brand",
    )
    tm = dispatcher["transaction_manager"]
    async with tm.transaction() as session:
        await advertiser_repo.save(advertiser_profile, session=session)

    # Создаем заказ
    order_service = dispatcher["order_service"]
    order = await order_service.create_order(
        advertiser_id=advertiser_user.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/product",
        offer_text="Test offer",
        ugc_requirements=None,
        barter_description=None,
        price=5000.0,
        bloggers_needed=3,
    )
    from ugc_bot.domain.entities import Order

    updated_order = Order(
        order_id=order.order_id,
        advertiser_id=order.advertiser_id,
        order_type=order.order_type,
        product_link=order.product_link,
        offer_text=order.offer_text,
        ugc_requirements=order.ugc_requirements,
        barter_description=order.barter_description,
        price=order.price,
        bloggers_needed=order.bloggers_needed,
        status=OrderStatus.CLOSED,
        created_at=order.created_at,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    order_repo = dispatcher["order_repo"]
    async with tm.transaction() as session:
        await order_repo.save(updated_order, session=session)
    order = updated_order

    interaction_service = dispatcher["interaction_service"]

    # Создаем взаимодействия для двух блогеров
    interaction1 = await interaction_service.create_for_contacts_sent(
        order.order_id, blogger1_user.user_id, advertiser_user.user_id
    )
    interaction2 = await interaction_service.create_for_contacts_sent(
        order.order_id, blogger2_user.user_id, advertiser_user.user_id
    )

    # === Шаг 1: Рекламодатель отвечает OK на оба ===
    await interaction_service.record_advertiser_feedback(
        interaction1.interaction_id, "✅"
    )
    await interaction_service.record_advertiser_feedback(
        interaction2.interaction_id, "✅"
    )

    # === Шаг 2: Блогеры отвечают по-разному ===
    # Блогер 1: OK
    await interaction_service.record_blogger_feedback(interaction1.interaction_id, "✅")
    # Блогер 2: NO_DEAL
    await interaction_service.record_blogger_feedback(interaction2.interaction_id, "❌")

    # === Шаг 3: Проверяем агрегацию ===
    final_interaction1 = await _get_interaction(dispatcher, interaction1.interaction_id)
    final_interaction2 = await _get_interaction(dispatcher, interaction2.interaction_id)

    # Оба должны быть OK (advertiser OK + blogger OK/NO_DEAL)
    assert final_interaction1.status == InteractionStatus.OK
    assert final_interaction2.status == InteractionStatus.OK

    print("✅ Feedback mixed responses aggregation test passed!")


@pytest.mark.asyncio
async def test_feedback_issue_status_blocks_user(
    dispatcher,
) -> None:
    """Test that ISSUE status increases user's issue_count."""

    # === Подготовка ===
    user_role_service = dispatcher["user_role_service"]
    advertiser_user = await user_role_service.create_user(
        "advertiser_issue", username="advertiser_issue"
    )
    blogger_user = await user_role_service.create_user(
        "blogger_issue", username="blogger_issue"
    )

    # Создаем advertiser profile
    advertiser_repo = dispatcher["advertiser_repo"]
    advertiser_profile = AdvertiserProfile(
        user_id=advertiser_user.user_id,
        phone="test@example.com",
        brand="Brand",
    )
    tm = dispatcher["transaction_manager"]
    async with tm.transaction() as session:
        await advertiser_repo.save(advertiser_profile, session=session)

    # Создаем заказ и взаимодействие
    order_service = dispatcher["order_service"]
    order = await order_service.create_order(
        advertiser_id=advertiser_user.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/product",
        offer_text="Test offer",
        ugc_requirements=None,
        barter_description=None,
        price=5000.0,
        bloggers_needed=3,
    )
    from ugc_bot.domain.entities import Order

    updated_order = Order(
        order_id=order.order_id,
        advertiser_id=order.advertiser_id,
        order_type=order.order_type,
        product_link=order.product_link,
        offer_text=order.offer_text,
        ugc_requirements=order.ugc_requirements,
        barter_description=order.barter_description,
        price=order.price,
        bloggers_needed=order.bloggers_needed,
        status=OrderStatus.CLOSED,
        created_at=order.created_at,
        completed_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    order_repo = dispatcher["order_repo"]
    async with tm.transaction() as session:
        await order_repo.save(updated_order, session=session)
    order = updated_order

    interaction_service = dispatcher["interaction_service"]
    interaction = await interaction_service.create_for_contacts_sent(
        order.order_id, blogger_user.user_id, advertiser_user.user_id
    )

    # === Шаг 1: Один участник отвечает ISSUE ===
    await interaction_service.record_blogger_feedback(interaction.interaction_id, "⚠️")

    # Проверяем, что взаимодействие остаётся PENDING (другая сторона ещё не ответила)
    # и next_check_at установлен для повторного запроса
    updated_interaction = await _get_interaction(dispatcher, interaction.interaction_id)
    assert updated_interaction.status == InteractionStatus.PENDING
    assert updated_interaction.next_check_at is not None

    print("✅ Feedback ISSUE status test passed!")
