"""Tests for admin moderation callback handler."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from tests.helpers.fakes import FakeCallback, FakeMessage, FakeUser
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.admin_moderation import handle_moderate_activate
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOrderRepository,
    InMemoryOutboxRepository,
    InMemoryUserRepository,
)


@pytest.fixture
def user_repo() -> InMemoryUserRepository:
    """User repository for tests."""
    return InMemoryUserRepository()


@pytest.fixture
def order_repo() -> InMemoryOrderRepository:
    """Order repository for tests."""
    return InMemoryOrderRepository()


@pytest.fixture
def outbox_repo() -> InMemoryOutboxRepository:
    """Outbox repository for tests."""
    return InMemoryOutboxRepository()


@pytest.fixture
def fake_tm():
    """Fake transaction manager."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _tx():
        yield object()

    class FakeTM:
        def transaction(self):
            return _tx()

    return FakeTM()


@pytest.fixture
def outbox_publisher(order_repo, outbox_repo, fake_tm) -> OutboxPublisher:
    """Outbox publisher with transaction manager."""
    return OutboxPublisher(
        outbox_repo=outbox_repo,
        order_repo=order_repo,
        transaction_manager=fake_tm,
    )


@pytest.mark.asyncio
async def test_handle_moderate_activate_success(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_repo: InMemoryOutboxRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Admin can activate order; outbox event is created."""
    admin = User(
        user_id=uuid4(),
        external_id="12345",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)

    order = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/product",
        offer_text="Test offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    message = FakeMessage()
    callback = FakeCallback(
        data=f"mod_activate:{order.order_id.hex}",
        user=FakeUser(12345, "admin"),
        message=message,
    )

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert callback.answers[0] == "Заказ активирован, уходит блогерам."
    events = await outbox_repo.get_pending_events()
    assert len(events) == 1
    assert events[0].payload["order_id"] == str(order.order_id)


@pytest.mark.asyncio
async def test_handle_moderate_activate_non_admin_rejected(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Non-admin gets access denied."""
    regular_user = User(
        user_id=uuid4(),
        external_id="99999",
        messenger_type=MessengerType.TELEGRAM,
        username="user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=False,
    )
    await user_repo.save(regular_user)

    order = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/product",
        offer_text="Test",
        barter_description=None,
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    callback = FakeCallback(
        data=f"mod_activate:{order.order_id.hex}",
        user=FakeUser(99999, "user"),
    )

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert callback.answers[0] == "Доступ запрещён."


@pytest.mark.asyncio
async def test_handle_moderate_activate_banned_content_rejected(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Order with banned content is not activated."""
    admin = User(
        user_id=uuid4(),
        external_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)

    order = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://1xbet.com/link",
        offer_text="Test",
        barter_description=None,
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    callback = FakeCallback(
        data=f"mod_activate:{order.order_id.hex}",
        user=FakeUser(111, "admin"),
    )

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert "Запрещённый контент" in callback.answers[0]
    assert "1xbet" in callback.answers[0]


@pytest.mark.asyncio
async def test_handle_moderate_activate_already_processed(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Already active order returns 'already processed' message."""
    admin = User(
        user_id=uuid4(),
        external_id="222",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)

    order = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/product",
        offer_text="Test",
        barter_description=None,
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    callback = FakeCallback(
        data=f"mod_activate:{order.order_id.hex}",
        user=FakeUser(222, "admin"),
    )

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert callback.answers[0] == "Заказ уже обработан."


@pytest.mark.asyncio
async def test_handle_moderate_activate_no_user_id(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Callback without from_user returns error."""
    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    callback = FakeCallback(
        data="mod_activate:" + uuid4().hex,
        user=None,  # type: ignore[arg-type]
    )
    callback.from_user = None

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert callback.answers[0] == "Ошибка: пользователь не определён."


@pytest.mark.asyncio
async def test_handle_moderate_activate_user_not_found(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """User not found in repository returns error."""
    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    callback = FakeCallback(
        data="mod_activate:" + uuid4().hex,
        user=FakeUser(99999, "unknown"),
    )

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert callback.answers[0] == "Пользователь не найден."


@pytest.mark.asyncio
async def test_handle_moderate_activate_invalid_order_id_format(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Invalid order ID format returns error."""
    admin = User(
        user_id=uuid4(),
        external_id="333",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)

    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    # Invalid format: wrong prefix
    callback = FakeCallback(
        data="invalid_prefix:12345",
        user=FakeUser(333, "admin"),
    )

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert callback.answers[0] == "Неверный формат идентификатора заказа."


@pytest.mark.asyncio
async def test_handle_moderate_activate_empty_data(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Empty callback data returns error."""
    admin = User(
        user_id=uuid4(),
        external_id="444",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)

    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    callback = FakeCallback(
        data="",  # Empty data
        user=FakeUser(444, "admin"),
    )

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert callback.answers[0] == "Неверный формат идентификатора заказа."


@pytest.mark.asyncio
async def test_handle_moderate_activate_none_data(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """None callback data returns error."""
    admin = User(
        user_id=uuid4(),
        external_id="445",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)

    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    callback = FakeCallback(
        data="mod_activate:" + uuid4().hex,
        user=FakeUser(445, "admin"),
    )
    callback.data = None  # type: ignore[assignment]

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert callback.answers[0] == "Неверный формат идентификатора заказа."


@pytest.mark.asyncio
async def test_handle_moderate_activate_order_id_wrong_length(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Order ID with wrong length returns error."""
    admin = User(
        user_id=uuid4(),
        external_id="444",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)

    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    # Wrong length: should be 32 hex chars
    callback = FakeCallback(
        data="mod_activate:12345",  # Too short
        user=FakeUser(444, "admin"),
    )

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert callback.answers[0] == "Неверный формат идентификатора заказа."


@pytest.mark.asyncio
async def test_handle_moderate_activate_order_id_invalid_hex(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Order ID with invalid hex characters returns error."""
    admin = User(
        user_id=uuid4(),
        external_id="555",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)

    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    # Invalid hex: contains 'g' which is not a valid hex character
    callback = FakeCallback(
        data="mod_activate:" + "g" * 32,
        user=FakeUser(555, "admin"),
    )

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert callback.answers[0] == "Неверный формат идентификатора заказа."


@pytest.mark.asyncio
async def test_handle_moderate_activate_order_not_found(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Order not found in repository returns error."""
    admin = User(
        user_id=uuid4(),
        external_id="666",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)

    user_role_service = UserRoleService(user_repo=user_repo)
    content_moderation = ContentModerationService()
    # Valid format but order doesn't exist
    non_existent_order_id = uuid4()
    callback = FakeCallback(
        data=f"mod_activate:{non_existent_order_id.hex}",
        user=FakeUser(666, "admin"),
    )

    await handle_moderate_activate(
        callback,
        user_role_service=user_role_service,
        content_moderation_service=content_moderation,
        order_repo=order_repo,
        outbox_publisher=outbox_publisher,
        transaction_manager=fake_tm,
    )

    assert len(callback.answers) == 1
    assert callback.answers[0] == "Заказ не найден."


@pytest.mark.asyncio
async def test_remove_moderation_keyboard_no_message(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_repo: InMemoryOutboxRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Removing keyboard when message has no edit_reply_markup doesn't fail."""
    from ugc_bot.bot.handlers.admin_moderation import (
        _remove_moderation_keyboard,
    )

    admin = User(
        user_id=uuid4(),
        external_id="777",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)

    order = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/product",
        offer_text="Test offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    # Message without edit_reply_markup method
    # Create a message-like object without edit_reply_markup
    class MessageWithoutEdit:
        pass

    message = MessageWithoutEdit()
    callback = FakeCallback(
        data=f"mod_activate:{order.order_id.hex}",
        user=FakeUser(777, "admin"),
        message=message,
    )

    # Should not raise exception
    await _remove_moderation_keyboard(callback)


@pytest.mark.asyncio
async def test_remove_moderation_keyboard_no_message_object(
    user_repo: InMemoryUserRepository,
    order_repo: InMemoryOrderRepository,
    outbox_repo: InMemoryOutboxRepository,
    outbox_publisher: OutboxPublisher,
    fake_tm: object,
) -> None:
    """Removing keyboard when callback has no message doesn't fail."""
    from ugc_bot.bot.handlers.admin_moderation import (
        _remove_moderation_keyboard,
    )

    callback = FakeCallback(
        data="mod_activate:" + uuid4().hex,
        user=FakeUser(888, "admin"),
    )
    callback.message = None

    # Should not raise exception
    await _remove_moderation_keyboard(callback)
