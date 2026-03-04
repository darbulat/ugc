"""Tests for payment handlers."""

from uuid import UUID

import pytest

from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_contact_pricing,
    create_test_order,
    create_test_user,
)
from tests.helpers.fakes import (
    FakeBot,
    FakeCallback,
    FakeMessage,
    FakePreCheckoutQuery,
    FakeSuccessfulPayment,
    FakeUser,
)
from tests.helpers.services import (
    build_contact_pricing_service,
    build_payment_service,
    build_profile_service,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.payments import (
    pay_order,
    pay_order_callback,
    pre_checkout_query_handler,
    send_order_invoice,
    successful_payment_handler,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import OrderStatus


class FakeConfig(AppConfig):
    """Config stub with provider token."""


class DummyPaymentProvider:
    """PaymentProvider stub for pre-checkout tests."""

    def __init__(self) -> None:
        self.confirmed: list[str] = []
        self.rejected: list[tuple[str, str]] = []

    async def confirm_pre_checkout(self, *, query_id: str) -> None:
        self.confirmed.append(query_id)

    async def reject_pre_checkout(
        self, *, query_id: str, error_message: str
    ) -> None:
        self.rejected.append((query_id, error_message))


@pytest.mark.asyncio
async def test_pay_order_success(
    monkeypatch: pytest.MonkeyPatch,
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Invoice is sent when order is valid."""

    from uuid import UUID

    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000500"),
        external_id="1",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await user_service.set_user(
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    order = await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000501"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )

    bot = FakeBot()
    message = FakeMessage(
        text=f"/pay_order {order.order_id}",
        user=FakeUser(1, "adv", "Adv"),
        bot=bot,
    )

    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order(
        message,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
    )
    assert bot.invoices


@pytest.mark.asyncio
async def test_pay_order_missing_provider_token(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject when provider token missing."""

    from datetime import datetime, timezone
    from uuid import UUID

    from ugc_bot.domain.entities import ContactPricing
    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    # Override price for 3 bloggers to be positive so provider check is needed
    await contact_pricing_service.pricing_repo.save(
        ContactPricing(
            bloggers_count=3, price=100.0, updated_at=datetime.now(timezone.utc)
        )
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000502"),
        external_id="2",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await user_service.set_user(
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000503"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )

    message = FakeMessage(
        text="/pay_order 00000000-0000-0000-0000-000000000503",
        user=FakeUser(2, "adv", "Adv"),
        bot=FakeBot(),
    )
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "",
        }
    )

    await pay_order(
        message,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
    )
    assert "Платежный провайдер не настроен." in message.answers[0]


@pytest.mark.asyncio
async def test_pay_order_invalid_args(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject missing order id argument."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000510"),
        external_id="10",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    message = FakeMessage(
        text="/pay_order", user=FakeUser(10, "adv", "Adv"), bot=None
    )
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order(
        message,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
    )
    assert "Использование" in message.answers[0]


@pytest.mark.asyncio
async def test_pay_order_invalid_uuid(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject invalid order id format."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000511"),
        external_id="11",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    message = FakeMessage(
        text="/pay_order not-a-uuid", user=FakeUser(11, "adv", "Adv"), bot=None
    )
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order(
        message,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
    )
    assert "Неверный формат" in message.answers[0]


@pytest.mark.asyncio
async def test_pay_order_order_not_found(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject missing order."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000512"),
        external_id="12",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    message = FakeMessage(
        text="/pay_order 00000000-0000-0000-0000-000000000599",
        user=FakeUser(12, "adv", "Adv"),
        bot=None,
    )
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order(
        message,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
    )
    assert "Заказ не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_pay_order_wrong_owner(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject payments for чужие заказы."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000513"),
        external_id="13",
    )
    other = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000514"),
        external_id="14",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    await create_test_order(
        order_repo,
        other.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000515"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )

    message = FakeMessage(
        text="/pay_order 00000000-0000-0000-0000-000000000515",
        user=FakeUser(13, "adv", "Adv"),
        bot=None,
    )
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order(
        message,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
    )
    assert "не принадлежит" in message.answers[0]


@pytest.mark.asyncio
async def test_pay_order_not_new_status(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject payments for non-NEW orders."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000516"),
        external_id="15",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000517"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
    )
    message = FakeMessage(
        text="/pay_order 00000000-0000-0000-0000-000000000517",
        user=FakeUser(15, "adv", "Adv"),
        bot=None,
    )
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order(
        message,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
    )
    assert "статусе NEW" in message.answers[0]


@pytest.mark.asyncio
async def test_pay_order_blocked_user(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject blocked users."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    from ugc_bot.domain.enums import UserStatus

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000518"),
        external_id="16",
        username="adv",
        status=UserStatus.BLOCKED,
    )
    message = FakeMessage(
        text="/pay_order 00000000-0000-0000-0000-000000000517",
        user=FakeUser(16, "adv", "Adv"),
        bot=None,
    )
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order(
        message,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
    )
    assert "Заблокированные" in message.answers[0]


@pytest.mark.asyncio
async def test_pay_order_paused_user(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject paused users."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    from ugc_bot.domain.enums import UserStatus

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000519"),
        external_id="17",
        username="adv",
        status=UserStatus.PAUSE,
    )
    message = FakeMessage(
        text="/pay_order 00000000-0000-0000-0000-000000000517",
        user=FakeUser(17, "adv", "Adv"),
        bot=None,
    )
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order(
        message,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
    )
    assert "на паузе" in message.answers[0]


@pytest.mark.asyncio
async def test_pay_order_missing_profile(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject missing advertiser profile."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000521"),
        external_id="21",
    )
    message = FakeMessage(
        text="/pay_order 00000000-0000-0000-0000-000000000517",
        user=FakeUser(21, "adv", "Adv"),
        bot=None,
    )
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order(
        message,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
    )
    assert "Профиль рекламодателя" in message.answers[0]


@pytest.mark.asyncio
async def test_pre_checkout_query_ok(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
) -> None:
    """Confirm pre-checkout query."""

    bot = FakeBot()
    query = FakePreCheckoutQuery("q1", bot)
    provider = DummyPaymentProvider()
    await pre_checkout_query_handler(query, payment_provider=provider)
    assert provider.confirmed == ["q1"]


@pytest.mark.asyncio
async def test_pre_checkout_query_without_bot(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
) -> None:
    """Skip when bot is missing."""

    query = FakePreCheckoutQuery("q1", None)
    provider = DummyPaymentProvider()
    await pre_checkout_query_handler(query, payment_provider=provider)
    assert provider.confirmed == ["q1"]


@pytest.mark.asyncio
async def test_successful_payment_handler(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Confirm payment on successful payment message."""

    await create_test_contact_pricing(
        pricing_repo, bloggers_count=3, price=1000.0
    )
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000504"),
        external_id="3",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    order = await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000505"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )

    bot = FakeBot()
    message = FakeMessage(
        text=None,
        user=FakeUser(3, "adv", "Adv"),
        bot=bot,
    )
    message.successful_payment = FakeSuccessfulPayment(
        payload=str(order.order_id), charge_id="charge_1"
    )

    content_moderation = ContentModerationService()
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    await successful_payment_handler(
        message,
        user_service,
        payment_service,
        content_moderation,
        config,
        bot_texts_service=bot_texts_service,
    )
    assert message.answers

    # Order goes to PENDING_MODERATION after payment
    fetched_order = await order_repo.get_by_id(order.order_id)
    assert fetched_order is not None
    assert fetched_order.status == OrderStatus.PENDING_MODERATION


@pytest.mark.asyncio
async def test_successful_payment_invalid_payload(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject invalid payload."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000520"),
        external_id="20",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    message = FakeMessage(
        text=None, user=FakeUser(20, "adv", "Adv"), bot=FakeBot()
    )
    message.successful_payment = FakeSuccessfulPayment(
        payload="bad", charge_id="c"
    )
    content_moderation = ContentModerationService()
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    await successful_payment_handler(
        message,
        user_service,
        payment_service,
        content_moderation,
        config,
        bot_texts_service=bot_texts_service,
    )
    assert "Не удалось определить заказ" in message.answers[0]


@pytest.mark.asyncio
async def test_successful_payment_user_not_found(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject when user is not found."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )

    message = FakeMessage(
        text=None, user=FakeUser(22, "adv", "Adv"), bot=FakeBot()
    )
    message.successful_payment = FakeSuccessfulPayment(
        payload="00000000-0000-0000-0000-000000000600", charge_id="c"
    )
    content_moderation = ContentModerationService()
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    await successful_payment_handler(
        message,
        user_service,
        payment_service,
        content_moderation,
        config,
        bot_texts_service=bot_texts_service,
    )
    msg = message.answers[0]
    assert "не найден" in msg or "not found" in msg.lower()


@pytest.mark.asyncio
async def test_send_order_invoice_bot_none_returns_early(
    messenger_client, event_adapter, bot_texts_service
) -> None:
    """send_order_invoice returns when message.bot is None."""
    message = FakeMessage(text="/pay", user=FakeUser(1), bot=None)
    message.chat = type("Chat", (), {"id": 1})()
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    incoming = event_adapter.from_message(message)
    await send_order_invoice(
        incoming,
        messenger_client,
        UUID("00000000-0000-0000-0000-000000000530"),
        "Offer",
        1000.0,
        config,
        bot_texts_service,
    )
    assert not message.answers


@pytest.mark.asyncio
async def test_send_order_invoice_no_chat_id_returns_early(
    messenger_client, bot_texts_service
) -> None:
    """send_order_invoice returns without sending when chat_id is falsy."""
    from ugc_bot.application.messenger.dto import IncomingMessage, IncomingUser
    from ugc_bot.domain.enums import MessengerType

    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    incoming = IncomingMessage(
        chat_id="",
        user=IncomingUser(
            external_id="1", messenger_type=MessengerType.TELEGRAM
        ),
        text=None,
    )
    await send_order_invoice(
        incoming,
        messenger_client,
        UUID("00000000-0000-0000-0000-000000000531"),
        "Offer",
        1000.0,
        config,
        bot_texts_service,
    )
    assert len(messenger_client.sent_text) == 0


@pytest.mark.asyncio
async def test_send_order_invoice_price_too_large(
    messenger_client, event_adapter, bot_texts_service
) -> None:
    """send_order_invoice rejects price over 100M."""
    bot = FakeBot()
    message = FakeMessage(text="/pay", user=FakeUser(1), bot=bot)
    message.chat = type("Chat", (), {"id": 1})()
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    incoming = event_adapter.from_message(message)
    await send_order_invoice(
        incoming,
        messenger_client,
        UUID("00000000-0000-0000-0000-000000000532"),
        "Offer",
        150_000_000.0,
        config,
        bot_texts_service,
    )
    assert "слишком большая" in message.answers[0]


@pytest.mark.asyncio
async def test_successful_payment_handler_no_payment_returns(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """successful_payment_handler returns when successful_payment is None."""
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000522"),
        external_id="22",
    )
    message = FakeMessage(
        text=None, user=FakeUser(22, "adv", "Adv"), bot=FakeBot()
    )
    message.successful_payment = None

    content_moderation = ContentModerationService()
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    await successful_payment_handler(
        message,
        user_service,
        payment_service,
        content_moderation,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert not message.answers


@pytest.mark.asyncio
async def test_send_order_invoice_invalid_price(
    messenger_client, event_adapter, bot_texts_service
) -> None:
    """send_order_invoice rejects invalid price (InvalidOperation)."""

    class BadPrice:
        def __str__(self) -> str:
            return "not-a-number"

    bot = FakeBot()
    message = FakeMessage(text="/pay", user=FakeUser(1), bot=bot)
    message.chat = type("Chat", (), {"id": 1})()
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    incoming = event_adapter.from_message(message)
    await send_order_invoice(
        incoming,
        messenger_client,
        UUID("00000000-0000-0000-0000-000000000533"),
        "Offer",
        BadPrice(),
        config,
        bot_texts_service,
    )
    assert message.answers
    assert "Некорректная сумма" in message.answers[0]


class FakeBotRaisingInvoice(FakeBot):
    """Fake bot that raises when send_invoice is called."""

    async def send_invoice(self, **kwargs: object) -> None:
        raise RuntimeError("send_invoice failed")


@pytest.mark.asyncio
async def test_send_order_invoice_send_fails(
    event_adapter, bot_texts_service
) -> None:
    """send_order_invoice handles send_invoice exception."""

    class FailingMessengerClient:
        def __init__(self, msg: FakeMessage) -> None:
            self._msg = msg

        async def send_invoice(self, *, chat_id: str, invoice) -> None:  # type: ignore[no-untyped-def]
            raise RuntimeError("send_invoice failed")

        async def send_text(self, *, chat_id: str, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self._msg.answers.append(text)

    message = FakeMessage(
        text="/pay", user=FakeUser(1), bot=FakeBotRaisingInvoice()
    )
    message.chat = type("Chat", (), {"id": 1})()
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    incoming = event_adapter.from_message(message)
    await send_order_invoice(
        incoming,
        FailingMessengerClient(message),
        UUID("00000000-0000-0000-0000-000000000534"),
        "Offer",
        1000.0,
        config,
        bot_texts_service,
    )
    assert message.answers
    assert "Не удалось создать счет" in message.answers[0]


@pytest.mark.asyncio
async def test_pay_order_contact_price_not_configured(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Reject when contact pricing is not configured for bloggers count."""

    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        {3: 100.0}, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000535"),
        external_id="23",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await user_service.set_user(
        external_id="23",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    order = await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000536"),
        price=1000.0,
        bloggers_needed=99,
        status=OrderStatus.NEW,
    )

    message = FakeMessage(
        text=f"/pay_order {order.order_id}",
        user=FakeUser(23, "adv", "Adv"),
        bot=FakeBot(),
    )
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order(
        message,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
    )
    assert message.answers
    assert (
        "Стоимость доступа" in message.answers[0]
        or "настроена" in message.answers[0]
    )


@pytest.mark.asyncio
async def test_successful_payment_handler_confirmation_error_with_metrics(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    bot_texts_service,
) -> None:
    """Payment handler records metric when confirm raises OrderCreationError."""

    from ugc_bot.application.errors import OrderCreationError

    class FakeMetricsCollector:
        def __init__(self) -> None:
            self.recorded: list[dict] = []

        def record_payment_failed(self, order_id: str, reason: str) -> None:
            self.recorded.append({"order_id": order_id, "reason": reason})

    class FailingPaymentService:
        def __init__(self, metrics_collector: FakeMetricsCollector) -> None:
            self.metrics_collector = metrics_collector

        async def confirm_telegram_payment(self, **kwargs: object) -> None:
            raise OrderCreationError("Order not found.")

    user_service = UserRoleService(user_repo=user_repo)
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000537"),
        external_id="24",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    metrics = FakeMetricsCollector()
    payment_service = FailingPaymentService(metrics_collector=metrics)

    message = FakeMessage(
        text=None, user=FakeUser(24, "adv", "Adv"), bot=FakeBot()
    )
    message.successful_payment = FakeSuccessfulPayment(
        payload="00000000-0000-0000-0000-000000000538", charge_id="charge_1"
    )

    content_moderation = ContentModerationService()
    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    with pytest.raises(OrderCreationError):
        await successful_payment_handler(
            message,
            user_service,
            payment_service,
            content_moderation,
            config,
            bot_texts_service=bot_texts_service,
        )

    assert len(metrics.recorded) == 1
    assert (
        metrics.recorded[0]["order_id"]
        == "00000000-0000-0000-0000-000000000538"
    )
    assert "Order not found" in metrics.recorded[0]["reason"]


@pytest.mark.asyncio
async def test_pay_order_callback_success(
    monkeypatch: pytest.MonkeyPatch,
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    messenger_client,
    event_adapter,
    bot_texts_service,
) -> None:
    """pay_order_callback sends invoice when order is valid."""
    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000540"),
        external_id="40",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await user_service.set_user(
        external_id="40",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    order = await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000541"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )

    bot = FakeBot()
    message = FakeMessage(user=FakeUser(40, "adv", "Adv"), bot=bot)
    message.chat = type("Chat", (), {"id": 40})()
    callback = FakeCallback(
        data=f"pay_order:{order.order_id}",
        user=FakeUser(40, "adv", "Adv"),
        message=message,
        bot=bot,
    )

    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order_callback(
        callback,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert len(messenger_client.sent_invoices) == 1
    assert messenger_client.sent_invoices[0]["invoice"].payload == str(
        order.order_id
    )


@pytest.mark.asyncio
async def test_pay_order_callback_order_not_new(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    messenger_client,
    event_adapter,
    bot_texts_service,
) -> None:
    """pay_order_callback rejects non-NEW order."""
    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000542"),
        external_id="41",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await user_service.set_user(
        external_id="41",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    order = await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000543"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
    )

    message = FakeMessage(user=FakeUser(41, "adv", "Adv"), bot=FakeBot())
    message.chat = type("Chat", (), {"id": 41})()
    callback = FakeCallback(
        data=f"pay_order:{order.order_id}",
        user=FakeUser(41, "adv", "Adv"),
        message=message,
    )

    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order_callback(
        callback,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert len(messenger_client.sent_invoices) == 0
    assert any("статусе NEW" in s["text"] for s in messenger_client.sent_text)


@pytest.mark.asyncio
async def test_pay_order_callback_invalid_uuid(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    messenger_client,
    event_adapter,
    bot_texts_service,
) -> None:
    """pay_order_callback rejects invalid order id in callback data."""
    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000544"),
        external_id="42",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await user_service.set_user(
        external_id="42",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    message = FakeMessage(user=FakeUser(42, "adv", "Adv"), bot=FakeBot())
    message.chat = type("Chat", (), {"id": 42})()
    callback = FakeCallback(
        data="pay_order:not-a-uuid",
        user=FakeUser(42, "adv", "Adv"),
        message=message,
    )

    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order_callback(
        callback,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert len(messenger_client.sent_invoices) == 0
    assert any(
        "Неверный формат" in s["text"] for s in messenger_client.sent_text
    )


@pytest.mark.asyncio
async def test_pay_order_callback_order_not_found(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    messenger_client,
    event_adapter,
    bot_texts_service,
) -> None:
    """pay_order_callback rejects when order does not exist."""
    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000545"),
        external_id="43",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await user_service.set_user(
        external_id="43",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    message = FakeMessage(user=FakeUser(43, "adv", "Adv"), bot=FakeBot())
    message.chat = type("Chat", (), {"id": 43})()
    callback = FakeCallback(
        data="pay_order:00000000-0000-0000-0000-000000000599",
        user=FakeUser(43, "adv", "Adv"),
        message=message,
    )

    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order_callback(
        callback,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert len(messenger_client.sent_invoices) == 0
    assert any(
        "Заказ не найден" in s["text"] for s in messenger_client.sent_text
    )


@pytest.mark.asyncio
async def test_pay_order_callback_no_advertiser_profile(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    messenger_client,
    event_adapter,
    bot_texts_service,
) -> None:
    """pay_order_callback rejects when user has no advertiser profile."""
    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000546"),
        external_id="44",
        username="adv",
    )
    await user_service.set_user(
        external_id="44",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    order = await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000547"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )

    message = FakeMessage(user=FakeUser(44, "adv", "Adv"), bot=FakeBot())
    message.chat = type("Chat", (), {"id": 44})()
    callback = FakeCallback(
        data=f"pay_order:{order.order_id}",
        user=FakeUser(44, "adv", "Adv"),
        message=message,
    )

    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order_callback(
        callback,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert len(messenger_client.sent_invoices) == 0
    assert any(
        "Профиль рекламодателя" in s["text"] for s in messenger_client.sent_text
    )


@pytest.mark.asyncio
async def test_pay_order_callback_wrong_owner(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    messenger_client,
    event_adapter,
    bot_texts_service,
) -> None:
    """pay_order_callback rejects when order belongs to another advertiser."""
    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000548"),
        external_id="45",
        username="adv1",
    )
    other = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000549"),
        external_id="46",
        username="adv2",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await user_service.set_user(
        external_id="45",
        messenger_type=MessengerType.TELEGRAM,
        username="adv1",
    )

    order = await create_test_order(
        order_repo,
        other.user_id,
        order_id=UUID("00000000-0000-0000-0000-00000000054a"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )

    message = FakeMessage(user=FakeUser(45, "adv1", "Adv1"), bot=FakeBot())
    message.chat = type("Chat", (), {"id": 45})()
    callback = FakeCallback(
        data=f"pay_order:{order.order_id}",
        user=FakeUser(45, "adv1", "Adv1"),
        message=message,
    )

    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )

    await pay_order_callback(
        callback,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert len(messenger_client.sent_invoices) == 0
    assert any(
        "не принадлежит" in s["text"] for s in messenger_client.sent_text
    )


@pytest.mark.asyncio
async def test_pay_order_callback_no_provider_token(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
    messenger_client,
    event_adapter,
    bot_texts_service,
) -> None:
    """pay_order_callback rejects when provider token is not configured."""
    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    contact_pricing_service = await build_contact_pricing_service(
        None, pricing_repo
    )

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000054b"),
        external_id="47",
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    await user_service.set_user(
        external_id="47",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    order = await create_test_order(
        order_repo,
        user.user_id,
        order_id=UUID("00000000-0000-0000-0000-00000000054c"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )

    message = FakeMessage(user=FakeUser(47, "adv", "Adv"), bot=FakeBot())
    message.chat = type("Chat", (), {"id": 47})()
    callback = FakeCallback(
        data=f"pay_order:{order.order_id}",
        user=FakeUser(47, "adv", "Adv"),
        message=message,
    )

    config = FakeConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "",
        }
    )

    await pay_order_callback(
        callback,
        user_service,
        profile_service,
        payment_service,
        contact_pricing_service,
        config,
        bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert len(messenger_client.sent_invoices) == 0
    assert any(
        "Платежный провайдер" in s["text"] for s in messenger_client.sent_text
    )
