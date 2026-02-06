"""Tests for admin notification service."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_complaint,
    notify_admins_about_new_order,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import Complaint, Order, User
from ugc_bot.domain.enums import (
    ComplaintStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


class FakeBot:
    """Bot stub that captures send_message and send_photo calls."""

    def __init__(self) -> None:
        self.messages: list[tuple[int, str, object]] = []
        self.photos: list[tuple[int, str, str | None, object]] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: object = None,
        **kwargs: object,
    ) -> None:
        self.messages.append((chat_id, text, reply_markup))

    async def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        reply_markup: object = None,
        **kwargs: object,
    ) -> None:
        self.photos.append((chat_id, photo, caption, reply_markup))


def _make_complaint(
    reporter_id: UUID | None = None,
    reported_id: UUID | None = None,
    order_id: UUID | None = None,
    reason: str = "Test reason",
    file_ids: list[str] | None = None,
) -> Complaint:
    return Complaint(
        complaint_id=uuid4(),
        reporter_id=reporter_id or uuid4(),
        reported_id=reported_id or uuid4(),
        order_id=order_id or uuid4(),
        reason=reason,
        status=ComplaintStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        reviewed_at=None,
        file_ids=file_ids,
    )


@pytest.mark.asyncio
async def test_notify_admins_no_admins_returns_early() -> None:
    """When no Telegram admins exist, return without sending."""
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    bot = FakeBot()
    complaint = _make_complaint()

    await notify_admins_about_complaint(complaint, bot, user_service)

    assert len(bot.messages) == 0
    assert len(bot.photos) == 0


@pytest.mark.asyncio
async def test_notify_admins_sends_message_when_no_photos() -> None:
    """When admins exist and no file_ids, send text message to each admin."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        external_id="123456789",
        messenger_type=MessengerType.TELEGRAM,
        username="admin1",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    bot = FakeBot()
    reporter = User(
        user_id=uuid4(),
        external_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="reporter",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    reported = User(
        user_id=uuid4(),
        external_id="222",
        messenger_type=MessengerType.TELEGRAM,
        username="reported",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(reporter)
    await user_repo.save(reported)
    complaint = _make_complaint(
        reporter_id=reporter.user_id,
        reported_id=reported.user_id,
        reason="Spam",
    )

    await notify_admins_about_complaint(complaint, bot, user_service)

    assert len(bot.messages) == 1
    chat_id, text, _ = bot.messages[0]
    assert chat_id == 123456789
    assert "Новая жалоба" in text
    assert "reporter" in text
    assert "reported" in text
    assert "Spam" in text


@pytest.mark.asyncio
async def test_notify_admins_sends_photos_when_file_ids_present() -> None:
    """When file_ids exist, send first photo with caption, then rest."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        external_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    bot = FakeBot()
    complaint = _make_complaint(
        reason="Bad content",
        file_ids=["photo1", "photo2", "photo3"],
    )

    await notify_admins_about_complaint(complaint, bot, user_service)

    assert len(bot.photos) == 3
    chat_id, photo1, caption, _ = bot.photos[0]
    assert chat_id == 999
    assert photo1 == "photo1"
    assert caption is not None
    assert "Новая жалоба" in caption
    assert "3 шт" in caption
    assert bot.photos[1] == (999, "photo2", None, None)
    assert bot.photos[2] == (999, "photo3", None, None)


@pytest.mark.asyncio
async def test_notify_admins_uses_id_when_user_not_found() -> None:
    """When reporter/reported not in repo, use complaint id in message."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    bot = FakeBot()
    reporter_id = uuid4()
    reported_id = uuid4()
    complaint = _make_complaint(
        reporter_id=reporter_id,
        reported_id=reported_id,
        reason="Issue",
    )

    await notify_admins_about_complaint(complaint, bot, user_service)

    assert len(bot.messages) == 1
    _, text, _ = bot.messages[0]
    assert str(reporter_id) in text
    assert str(reported_id) in text


@pytest.mark.asyncio
async def test_notify_admins_continues_on_send_failure() -> None:
    """When send fails for one admin, log and continue to next."""
    user_repo = InMemoryUserRepository()
    admin1 = User(
        user_id=uuid4(),
        external_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="a1",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    admin2 = User(
        user_id=uuid4(),
        external_id="222",
        messenger_type=MessengerType.TELEGRAM,
        username="a2",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin1)
    await user_repo.save(admin2)
    user_service = UserRoleService(user_repo=user_repo)
    complaint = _make_complaint(reason="Test")

    messages: list[tuple[int, str]] = []

    class FailingBot:
        async def send_message(
            self, chat_id: int, text: str, **kwargs: object
        ) -> None:
            if chat_id == 111:
                raise RuntimeError("Network error")
            messages.append((chat_id, text))

    bot = FailingBot()
    await notify_admins_about_complaint(complaint, bot, user_service)

    assert len(messages) == 1
    assert messages[0][0] == 222


def _make_order(
    order_id: UUID | None = None,
    advertiser_id: UUID | None = None,
    offer_text: str = "Test offer",
) -> Order:
    return Order(
        order_id=order_id or uuid4(),
        advertiser_id=advertiser_id or uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/product",
        offer_text=offer_text,
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )


@pytest.mark.asyncio
async def test_notify_admins_about_new_order_no_admins() -> None:
    """When no admins, return without sending."""
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    bot = FakeBot()
    content_moderation = ContentModerationService()
    order = _make_order()

    await notify_admins_about_new_order(
        order, bot, user_service, content_moderation
    )

    assert len(bot.messages) == 0
    assert len(bot.photos) == 0


@pytest.mark.asyncio
async def test_notify_admins_about_new_order_sends_message() -> None:
    """When admins exist, send order details to each."""
    user_repo = InMemoryUserRepository()
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
    advertiser = User(
        user_id=uuid4(),
        external_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    user_service = UserRoleService(user_repo=user_repo)
    bot = FakeBot()
    content_moderation = ContentModerationService()
    order = _make_order(advertiser_id=advertiser.user_id)

    await notify_admins_about_new_order(
        order, bot, user_service, content_moderation
    )

    assert len(bot.messages) == 1
    chat_id, text, _ = bot.messages[0]
    assert chat_id == 12345
    assert "Новый заказ на модерацию" in text
    assert "advertiser" in text
    assert "Test offer" in text


@pytest.mark.asyncio
async def test_notify_admins_about_new_order_includes_admin_link() -> None:
    """When admin_base_url is set, message has InlineKeyboardButton with URL."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    user_repo = InMemoryUserRepository()
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
    advertiser = User(
        user_id=uuid4(),
        external_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    user_service = UserRoleService(user_repo=user_repo)
    bot = FakeBot()
    content_moderation = ContentModerationService()
    order = _make_order(advertiser_id=advertiser.user_id)

    await notify_admins_about_new_order(
        order,
        bot,
        user_service,
        content_moderation,
        admin_base_url="https://admin.example.com",
    )

    assert len(bot.messages) == 1
    _, text, reply_markup = bot.messages[0]
    assert "Новый заказ на модерацию" in text
    assert isinstance(reply_markup, InlineKeyboardMarkup)
    assert len(reply_markup.inline_keyboard) == 1
    btn = reply_markup.inline_keyboard[0][0]
    assert isinstance(btn, InlineKeyboardButton)
    assert btn.text == "Открыть в админке"
    assert (
        btn.url
        == f"https://admin.example.com/order-model/edit/{order.order_id}"
    )
