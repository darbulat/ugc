"""Tests for admin notification service."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from tests.helpers.fakes import FakeMessengerClient
from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_complaint,
    notify_admins_about_order_created,
    notify_admins_about_order_paid,
    notify_support_chat_about_new_order,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import (
    AdvertiserProfile,
    Complaint,
    Country,
    Order,
    User,
)
from ugc_bot.domain.enums import (
    ComplaintStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryCountryRepository,
    InMemoryUserRepository,
)


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
    messenger_client = FakeMessengerClient()
    complaint = _make_complaint()

    await notify_admins_about_complaint(
        complaint, messenger_client, user_service
    )

    assert len(messenger_client.sent_text) == 0
    assert len(messenger_client.sent_photos) == 0


@pytest.mark.asyncio
async def test_notify_admins_sends_message_when_no_photos() -> None:
    """When admins exist and no file_ids, send text message to each admin."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="123456789",
        messenger_type=MessengerType.TELEGRAM,
        username="admin1",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    reporter = User(
        user_id=uuid4(),
        telegram_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="reporter",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    reported = User(
        user_id=uuid4(),
        telegram_id="222",
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

    await notify_admins_about_complaint(
        complaint, messenger_client, user_service
    )

    assert len(messenger_client.sent_text) == 1
    first = messenger_client.sent_text[0]
    text = first["text"]
    assert first["chat_id"] == "123456789"
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
        telegram_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    complaint = _make_complaint(
        reason="Bad content",
        file_ids=["photo1", "photo2", "photo3"],
    )

    await notify_admins_about_complaint(
        complaint, messenger_client, user_service
    )

    assert len(messenger_client.sent_photos) == 3
    first = messenger_client.sent_photos[0]
    assert first["chat_id"] == "999"
    photo1 = first["file_id"]
    caption = first["caption"]
    assert photo1 == "photo1"
    assert caption is not None
    assert "Новая жалоба" in caption
    assert "3 шт" in caption
    assert messenger_client.sent_photos[1]["file_id"] == "photo2"
    assert messenger_client.sent_photos[1]["caption"] is None
    assert messenger_client.sent_photos[2]["file_id"] == "photo3"
    assert messenger_client.sent_photos[2]["caption"] is None


@pytest.mark.asyncio
async def test_notify_admins_uses_id_when_user_not_found() -> None:
    """When reporter/reported not in repo, use complaint id in message."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    reporter_id = uuid4()
    reported_id = uuid4()
    complaint = _make_complaint(
        reporter_id=reporter_id,
        reported_id=reported_id,
        reason="Issue",
    )

    await notify_admins_about_complaint(
        complaint, messenger_client, user_service
    )

    assert len(messenger_client.sent_text) == 1
    text = messenger_client.sent_text[0]["text"]
    assert str(reporter_id) in text
    assert str(reported_id) in text


@pytest.mark.asyncio
async def test_notify_admins_continues_on_send_failure() -> None:
    """When send fails for one admin, log and continue to next."""
    user_repo = InMemoryUserRepository()
    admin1 = User(
        user_id=uuid4(),
        telegram_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="a1",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    admin2 = User(
        user_id=uuid4(),
        telegram_id="222",
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
    barter_description: str | None = None,
    content_usage: str | None = None,
    deadlines: str | None = None,
    geography: str | None = None,
    product_photo_file_id: str | None = None,
    currency: str = "RUB",
) -> Order:
    return Order(
        order_id=order_id or uuid4(),
        advertiser_id=advertiser_id or uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com/product",
        offer_text=offer_text,
        barter_description=barter_description,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        content_usage=content_usage,
        deadlines=deadlines,
        geography=geography,
        product_photo_file_id=product_photo_file_id,
        currency=currency,
    )


@pytest.mark.asyncio
async def test_notify_admins_about_order_paid_no_admins() -> None:
    """When no admins, return without sending."""
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order()

    await notify_admins_about_order_paid(
        order, messenger_client, user_service, content_moderation
    )

    assert len(messenger_client.sent_text) == 0
    assert len(messenger_client.sent_photos) == 0


@pytest.mark.asyncio
async def test_notify_admins_about_order_paid_sends_message() -> None:
    """When admins exist, send order details to each."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="12345",
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
        telegram_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order(advertiser_id=advertiser.user_id)

    await notify_admins_about_order_paid(
        order, messenger_client, user_service, content_moderation
    )

    assert len(messenger_client.sent_text) == 1
    first = messenger_client.sent_text[0]
    text = first["text"]
    assert first["chat_id"] == "12345"
    assert "Заказ оплачен" in text
    assert "advertiser" in text
    assert "Test offer" in text


@pytest.mark.asyncio
async def test_notify_admins_about_order_paid_includes_admin_link() -> None:
    """When admin_base_url set, message has admin link and Activate button."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="111",
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
        telegram_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order(advertiser_id=advertiser.user_id)

    await notify_admins_about_order_paid(
        order,
        messenger_client,
        user_service,
        content_moderation,
        admin_base_url="https://admin.example.com",
    )

    assert len(messenger_client.sent_text) == 1
    first = messenger_client.sent_text[0]
    text = first["text"]
    reply_markup = first["keyboard"]
    assert "Заказ оплачен" in text
    rows = reply_markup.rows if reply_markup else []
    assert len(rows) >= 1
    admin_btn = rows[0][0]
    assert admin_btn.text == "Открыть в админке"
    assert (
        admin_btn.url
        == f"https://admin.example.com/order-model/edit/{order.order_id}"
    )
    activate_row = rows[-1]
    assert len(activate_row) == 1
    activate_btn = activate_row[0]
    assert activate_btn.text == "Активировать"
    assert activate_btn.callback_data == f"mod_activate:{order.order_id.hex}"


@pytest.mark.asyncio
async def test_notify_admins_about_order_paid_includes_all_fields() -> None:
    """Message includes all order fields: type, barter, content_usage, etc."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="555",
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
        telegram_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order(
        advertiser_id=advertiser.user_id,
        offer_text="Full offer text without truncation",
        barter_description="Product sample",
        content_usage="Stories and reels",
        deadlines="2 weeks",
        geography="Russia",
    )

    await notify_admins_about_order_paid(
        order, messenger_client, user_service, content_moderation
    )

    assert len(messenger_client.sent_text) == 1
    first = messenger_client.sent_text[0]
    text = first["text"]
    reply_markup = first["keyboard"]
    assert "Full offer text without truncation" in text
    assert "Product sample" in text
    assert "Stories and reels" in text
    assert "2 weeks" in text
    assert "Russia" in text
    assert "UGC-видео для бренда" in text
    assert reply_markup is not None
    rows = reply_markup.rows if reply_markup else []
    activate_btn = rows[0][0]
    assert activate_btn.text == "Активировать"


@pytest.mark.asyncio
async def test_notify_admins_about_order_paid_with_banned_content() -> None:
    """When order has banned content, message includes warning."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="111",
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
        telegram_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order(
        advertiser_id=advertiser.user_id,
        offer_text="1xbet casino gambling",
    )

    await notify_admins_about_order_paid(
        order, messenger_client, user_service, content_moderation
    )

    assert len(messenger_client.sent_text) == 1
    text = messenger_client.sent_text[0]["text"]
    assert "запрещённый контент" in text.lower()


@pytest.mark.asyncio
async def test_notify_admins_about_order_paid_with_product_photo() -> None:
    """When order has product_photo_file_id, send photo with caption."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="111",
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
        telegram_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order(
        advertiser_id=advertiser.user_id,
        product_photo_file_id="AgACAgIAAxkBAAI",
    )

    await notify_admins_about_order_paid(
        order, messenger_client, user_service, content_moderation
    )

    assert len(messenger_client.sent_photos) == 1
    assert messenger_client.sent_photos[0]["file_id"] == "AgACAgIAAxkBAAI"
    assert "Заказ оплачен" in messenger_client.sent_photos[0]["caption"]


@pytest.mark.asyncio
async def test_notify_admins_about_order_paid_continues_on_send_failure() -> (
    None
):
    """When send fails for one admin, log and continue to next."""
    user_repo = InMemoryUserRepository()
    admin1 = User(
        user_id=uuid4(),
        telegram_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="a1",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    admin2 = User(
        user_id=uuid4(),
        telegram_id="222",
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
    content_moderation = ContentModerationService()
    order = _make_order()

    messages: list[tuple[int, str]] = []

    class FailingBot:
        async def send_message(
            self, chat_id: int, text: str, **kwargs: object
        ) -> None:
            if chat_id == 111:
                raise RuntimeError("Network error")
            messages.append((chat_id, text))

    bot = FailingBot()
    await notify_admins_about_order_paid(
        order, bot, user_service, content_moderation
    )

    assert len(messages) == 1
    assert messages[0][0] == 222


@pytest.mark.asyncio
async def test_send_admin_text_raises_when_client_lacks_send_methods() -> None:
    """_send_admin_text raises when client has neither send_text nor send."""
    from ugc_bot.application.services.admin_notification_service import (
        _send_admin_text,
    )

    class NoSendClient:
        pass

    with pytest.raises(AttributeError, match="lacks send methods"):
        await _send_admin_text(
            NoSendClient(),
            chat_id="123",
            text="Test",
        )


@pytest.mark.asyncio
async def test_send_admin_photo_raises_when_client_lacks_send_photo() -> None:
    """_send_admin_photo raises when client has neither send_text nor send."""
    from ugc_bot.application.services.admin_notification_service import (
        _send_admin_photo,
    )

    class NoPhotoClient:
        pass

    with pytest.raises(AttributeError, match="lacks send_photo"):
        await _send_admin_photo(
            NoPhotoClient(),
            chat_id="123",
            file_id="photo123",
            caption="Test",
        )


@pytest.mark.asyncio
async def test_send_admin_photo_uses_raw_bot_send_photo() -> None:
    """_send_admin_photo uses send_photo when client has it (raw bot path)."""

    sent: list[dict[str, object]] = []

    class RawBotClient:
        async def send_photo(
            self,
            chat_id: int,
            photo: str,
            caption: str | None = None,
            reply_markup: object = None,
            parse_mode: str | None = None,
        ) -> None:
            sent.append(
                {
                    "chat_id": chat_id,
                    "photo": photo,
                    "caption": caption,
                    "reply_markup": reply_markup,
                    "parse_mode": parse_mode,
                }
            )

    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="777",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = RawBotClient()
    content_moderation = ContentModerationService()
    order = _make_order(product_photo_file_id="raw_photo_id")

    await notify_admins_about_order_paid(
        order, messenger_client, user_service, content_moderation
    )

    assert len(sent) == 1
    assert sent[0]["chat_id"] == 777
    assert sent[0]["photo"] == "raw_photo_id"
    assert sent[0]["caption"] is not None


# --- Tests for notify_admins_about_order_created ---


@pytest.mark.asyncio
async def test_notify_admins_about_order_created_no_admins() -> None:
    """When no admins, return without sending."""
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order()

    await notify_admins_about_order_created(
        order, messenger_client, user_service, content_moderation
    )

    assert len(messenger_client.sent_text) == 0
    assert len(messenger_client.sent_photos) == 0


@pytest.mark.asyncio
async def test_notify_admins_about_order_created_header() -> None:
    """Header contains 'Новый заказ' and does NOT contain 'на модерацию'."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="12345",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order()

    await notify_admins_about_order_created(
        order, messenger_client, user_service, content_moderation
    )

    assert len(messenger_client.sent_text) == 1
    text = messenger_client.sent_text[0]["text"]
    assert "Новый заказ" in text
    assert "на модерацию" not in text


@pytest.mark.asyncio
async def test_notify_admins_about_order_created_no_activate_button() -> None:
    """No 'Активировать' button in any keyboard row."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order()

    await notify_admins_about_order_created(
        order,
        messenger_client,
        user_service,
        content_moderation,
        admin_base_url="https://admin.example.com",
    )

    assert len(messenger_client.sent_text) == 1
    reply_markup = messenger_client.sent_text[0]["keyboard"]
    rows = reply_markup.rows if reply_markup else []
    all_buttons = [btn for row in rows for btn in row]
    assert not any(btn.text == "Активировать" for btn in all_buttons)


@pytest.mark.asyncio
async def test_notify_admins_about_order_created_open_in_admin_button() -> None:
    """'Открыть в админке' button present when admin_base_url is set."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order()

    await notify_admins_about_order_created(
        order,
        messenger_client,
        user_service,
        content_moderation,
        admin_base_url="https://admin.example.com",
    )

    reply_markup = messenger_client.sent_text[0]["keyboard"]
    rows = reply_markup.rows if reply_markup else []
    all_buttons = [btn for row in rows for btn in row]
    assert any(btn.text == "Открыть в админке" for btn in all_buttons)


@pytest.mark.asyncio
async def test_notify_admins_about_order_created_no_admin_url_no_keyboard() -> (
    None
):
    """No 'Открыть в админке' when admin_base_url is empty."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order()

    await notify_admins_about_order_created(
        order,
        messenger_client,
        user_service,
        content_moderation,
        admin_base_url="",
    )

    reply_markup = messenger_client.sent_text[0]["keyboard"]
    assert reply_markup is None


@pytest.mark.asyncio
async def test_notify_admins_about_order_created_with_product_photo() -> None:
    """When order has product_photo_file_id, send photo not text."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order(product_photo_file_id="photo_file_id_123")

    await notify_admins_about_order_created(
        order, messenger_client, user_service, content_moderation
    )

    assert len(messenger_client.sent_text) == 0
    assert len(messenger_client.sent_photos) == 1
    assert messenger_client.sent_photos[0]["file_id"] == "photo_file_id_123"
    assert "Новый заказ" in messenger_client.sent_photos[0]["caption"]


@pytest.mark.asyncio
async def test_notify_admins_about_order_created_with_banned_content() -> None:
    """When order has banned content, creation notification includes warning."""
    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order(offer_text="1xbet casino gambling")

    await notify_admins_about_order_created(
        order, messenger_client, user_service, content_moderation
    )

    assert len(messenger_client.sent_text) == 1
    text = messenger_client.sent_text[0]["text"]
    assert "запрещённый контент" in text.lower()


@pytest.mark.asyncio
async def test_notify_admins_about_order_created_continues_on_failure() -> None:
    """When send fails for one admin, log and continue to next."""
    user_repo = InMemoryUserRepository()
    admin1 = User(
        user_id=uuid4(),
        telegram_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="a1",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    admin2 = User(
        user_id=uuid4(),
        telegram_id="222",
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
    content_moderation = ContentModerationService()
    order = _make_order()

    messages: list[tuple[int, str]] = []

    class FailingBot:
        async def send_message(
            self, chat_id: int, text: str, **kwargs: object
        ) -> None:
            if chat_id == 111:
                raise RuntimeError("Network error")
            messages.append((chat_id, text))

    bot = FailingBot()
    await notify_admins_about_order_created(
        order, bot, user_service, content_moderation
    )

    assert len(messages) == 1
    assert messages[0][0] == 222


@pytest.mark.asyncio
async def test_notify_admins_about_order_paid_ugc_plus_placement() -> None:
    """Message includes 'UGC + размещение' for UGC_PLUS_PLACEMENT order type."""
    from ugc_bot.domain.enums import OrderType

    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_PLUS_PLACEMENT,
        product_link="https://example.com/product",
        offer_text="Test offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        content_usage=None,
        deadlines=None,
        geography=None,
        product_photo_file_id=None,
    )

    await notify_admins_about_order_paid(
        order, messenger_client, user_service, content_moderation
    )

    assert len(messenger_client.sent_text) == 1
    text = messenger_client.sent_text[0]["text"]
    assert "UGC + размещение" in text


# --- Tests for notify_support_chat_about_new_order ---


def _make_advertiser_user(
    user_id: UUID | None = None,
    telegram: str | None = "advertiser_tg",
) -> User:
    return User(
        user_id=user_id or uuid4(),
        telegram_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        telegram=telegram,
    )


def _make_advertiser_profile(user_id: UUID) -> AdvertiserProfile:
    return AdvertiserProfile(
        user_id=user_id,
        phone="+79001234567",
        brand="TestBrand",
    )


@pytest.mark.asyncio
async def test_notify_support_chat_skips_empty_chat_id() -> None:
    """When support_chat_id is empty, return without sending."""
    messenger_client = FakeMessengerClient()
    user = _make_advertiser_user()
    order = _make_order(advertiser_id=user.user_id)

    await notify_support_chat_about_new_order(
        order=order,
        advertiser_user=user,
        advertiser_profile=None,
        messenger_client=messenger_client,
        support_chat_id="",
    )

    assert len(messenger_client.sent_text) == 0


@pytest.mark.asyncio
async def test_notify_support_chat_sends_order_details() -> None:
    """When support_chat_id set, send order details with phone and telegram."""
    messenger_client = FakeMessengerClient()
    user = _make_advertiser_user()
    profile = _make_advertiser_profile(user.user_id)
    order = _make_order(
        advertiser_id=user.user_id,
        offer_text="Make a review video",
    )

    await notify_support_chat_about_new_order(
        order=order,
        advertiser_user=user,
        advertiser_profile=profile,
        messenger_client=messenger_client,
        support_chat_id="-1001234567890",
    )

    assert len(messenger_client.sent_text) == 1
    msg = messenger_client.sent_text[0]
    assert msg["chat_id"] == "-1001234567890"
    text = msg["text"]
    assert "Новый заказ" in text
    assert "+79001234567" in text
    assert "@advertiser_tg" in text
    assert "Make a review video" in text
    assert msg["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_notify_support_chat_includes_admin_link() -> None:
    """When admin_base_url set, message includes admin link button."""
    messenger_client = FakeMessengerClient()
    user = _make_advertiser_user()
    profile = _make_advertiser_profile(user.user_id)
    order = _make_order(advertiser_id=user.user_id)

    await notify_support_chat_about_new_order(
        order=order,
        advertiser_user=user,
        advertiser_profile=profile,
        messenger_client=messenger_client,
        support_chat_id="-100123",
        admin_base_url="https://bot.usemycontent.ru/admin",
    )

    assert len(messenger_client.sent_text) == 1
    msg = messenger_client.sent_text[0]
    keyboard = msg["keyboard"]
    assert keyboard is not None
    rows = keyboard.rows
    assert len(rows) == 1
    btn = rows[0][0]
    assert btn.text == "Открыть в админке"
    assert (
        btn.url == f"https://bot.usemycontent.ru/admin/orders/{order.order_id}"
    )


@pytest.mark.asyncio
async def test_notify_support_chat_no_profile_shows_dash() -> None:
    """When advertiser_profile is None, phone shows dash."""
    messenger_client = FakeMessengerClient()
    user = _make_advertiser_user(telegram=None)
    order = _make_order(advertiser_id=user.user_id)

    await notify_support_chat_about_new_order(
        order=order,
        advertiser_user=user,
        advertiser_profile=None,
        messenger_client=messenger_client,
        support_chat_id="-100123",
    )

    assert len(messenger_client.sent_text) == 1
    text = messenger_client.sent_text[0]["text"]
    assert "<b>Телефон:</b> —" in text
    assert (
        '<b>Telegram:</b> <a href="tg://user?id=999">tg://user?id=999</a>'
        in text
    )


@pytest.mark.asyncio
async def test_notify_support_chat_handles_send_failure() -> None:
    """When send fails, log warning but do not raise."""

    class FailingClient:
        async def send_text(self, **kwargs: object) -> None:
            raise RuntimeError("Network error")

    client = FailingClient()
    user = _make_advertiser_user()
    order = _make_order(advertiser_id=user.user_id)

    # Should not raise
    await notify_support_chat_about_new_order(
        order=order,
        advertiser_user=user,
        advertiser_profile=None,
        messenger_client=client,
        support_chat_id="-100123",
    )


@pytest.mark.asyncio
async def test_notify_support_chat_resolves_currency_from_order() -> None:
    """Currency symbol resolved from order's currency via country_repo."""
    messenger_client = FakeMessengerClient()
    user = _make_advertiser_user()
    order = _make_order(advertiser_id=user.user_id, currency="USD")

    country_repo = InMemoryCountryRepository()
    from decimal import Decimal

    country_repo.countries["US"] = Country(
        code="US",
        name_native="United States",
        currency_code="USD",
        currency_symbol="$",
        tax_rate=Decimal("0"),
        enabled=True,
    )

    await notify_support_chat_about_new_order(
        order=order,
        advertiser_user=user,
        advertiser_profile=None,
        messenger_client=messenger_client,
        support_chat_id="-100123",
        currency_symbol="₽",  # default (wrong) symbol — should be overridden
        country_repo=country_repo,
    )

    assert len(messenger_client.sent_text) == 1
    text = messenger_client.sent_text[0]["text"]
    assert "1000.0 $" in text
    assert "₽" not in text


@pytest.mark.asyncio
async def test_notify_support_chat_non_digit_telegram_id_shows_dash() -> None:
    """When telegram is None and telegram_id is not a digit, shows dash."""
    messenger_client = FakeMessengerClient()
    user = User(
        user_id=uuid4(),
        telegram_id="non_digit",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        telegram=None,
    )
    order = _make_order(advertiser_id=user.user_id)

    await notify_support_chat_about_new_order(
        order=order,
        advertiser_user=user,
        advertiser_profile=None,
        messenger_client=messenger_client,
        support_chat_id="-100123",
    )

    text = messenger_client.sent_text[0]["text"]
    assert "<b>Telegram:</b> —" in text


@pytest.mark.asyncio
async def test_notify_admins_about_order_created_resolves_currency() -> None:
    """Currency symbol is resolved from country_repo when provided."""
    from decimal import Decimal

    user_repo = InMemoryUserRepository()
    admin = User(
        user_id=uuid4(),
        telegram_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )
    await user_repo.save(admin)
    user_service = UserRoleService(user_repo=user_repo)
    messenger_client = FakeMessengerClient()
    content_moderation = ContentModerationService()
    order = _make_order(currency="USD")

    country_repo = InMemoryCountryRepository()
    country_repo.countries["US"] = Country(
        code="US",
        name_native="United States",
        currency_code="USD",
        currency_symbol="$",
        tax_rate=Decimal("0"),
        enabled=True,
    )

    await notify_admins_about_order_created(
        order,
        messenger_client,
        user_service,
        content_moderation,
        currency_symbol="₽",
        country_repo=country_repo,
    )

    text = messenger_client.sent_text[0]["text"]
    assert "1000.0 $" in text
    assert "₽" not in text


@pytest.mark.asyncio
async def test_notify_support_chat_unknown_currency_uses_default() -> None:
    """When country not found for currency, default symbol is used."""
    messenger_client = FakeMessengerClient()
    user = _make_advertiser_user()
    order = _make_order(advertiser_id=user.user_id, currency="XYZ")

    country_repo = InMemoryCountryRepository()  # empty, no XYZ country

    await notify_support_chat_about_new_order(
        order=order,
        advertiser_user=user,
        advertiser_profile=None,
        messenger_client=messenger_client,
        support_chat_id="-100123",
        currency_symbol="₽",
        country_repo=country_repo,
    )

    text = messenger_client.sent_text[0]["text"]
    assert "₽" in text
