"""Tests for payment handlers."""

from uuid import UUID

import pytest

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.payments import (
    pay_order,
    pre_checkout_query_handler,
    successful_payment_handler,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import OrderStatus
from tests.helpers.fakes import (
    FakeBot,
    FakeMessage,
    FakePreCheckoutQuery,
    FakeSuccessfulPayment,
    FakeUser,
)
from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_order,
    create_test_user,
)
from tests.helpers.services import (
    build_contact_pricing_service,
    build_payment_service,
    build_profile_service,
)


class FakeConfig(AppConfig):
    """Config stub with provider token."""


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
) -> None:
    """Invoice is sent when order is valid."""

    from uuid import UUID
    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    contact_pricing_service = await build_contact_pricing_service(None, pricing_repo)

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
) -> None:
    """Reject when provider token missing."""

    from datetime import datetime, timezone
    from uuid import UUID
    from ugc_bot.domain.entities import ContactPricing
    from ugc_bot.domain.enums import MessengerType

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    contact_pricing_service = await build_contact_pricing_service(None, pricing_repo)

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
) -> None:
    """Reject missing order id argument."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    contact_pricing_service = await build_contact_pricing_service(None, pricing_repo)

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000510"),
        external_id="10",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    message = FakeMessage(text="/pay_order", user=FakeUser(10, "adv", "Adv"), bot=None)
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
) -> None:
    """Reject invalid order id format."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    contact_pricing_service = await build_contact_pricing_service(None, pricing_repo)

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
) -> None:
    """Reject missing order."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    contact_pricing_service = await build_contact_pricing_service(None, pricing_repo)

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
) -> None:
    """Reject payments for чужие заказы."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    contact_pricing_service = await build_contact_pricing_service(None, pricing_repo)

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
) -> None:
    """Reject payments for non-NEW orders."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    contact_pricing_service = await build_contact_pricing_service(None, pricing_repo)

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
) -> None:
    """Reject blocked users."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    contact_pricing_service = await build_contact_pricing_service(None, pricing_repo)

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
) -> None:
    """Reject paused users."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    contact_pricing_service = await build_contact_pricing_service(None, pricing_repo)

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
) -> None:
    """Reject missing advertiser profile."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )
    profile_service = build_profile_service(user_repo, advertiser_repo=advertiser_repo)
    contact_pricing_service = await build_contact_pricing_service(None, pricing_repo)

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
    await pre_checkout_query_handler(query)
    assert bot.pre_checkout_answers


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
    await pre_checkout_query_handler(query)


@pytest.mark.asyncio
async def test_successful_payment_handler(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
) -> None:
    """Confirm payment on successful payment message."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
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

    await successful_payment_handler(message, user_service, payment_service)
    assert message.answers

    # Order should still be NEW until outbox is processed
    fetched_order = await order_repo.get_by_id(order.order_id)
    assert fetched_order is not None
    assert fetched_order.status == OrderStatus.NEW

    # Process outbox events to activate order
    from ugc_bot.infrastructure.kafka.publisher import NoopOrderActivationPublisher

    kafka_publisher = NoopOrderActivationPublisher()
    await payment_service.outbox_publisher.process_pending_events(
        kafka_publisher, max_retries=3
    )

    # Now order should be activated
    fetched_order = await order_repo.get_by_id(order.order_id)
    assert fetched_order is not None
    assert fetched_order.status == OrderStatus.ACTIVE


@pytest.mark.asyncio
async def test_successful_payment_invalid_payload(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
    pricing_repo,
) -> None:
    """Reject invalid payload."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000520"),
        external_id="20",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    message = FakeMessage(text=None, user=FakeUser(20, "adv", "Adv"), bot=FakeBot())
    message.successful_payment = FakeSuccessfulPayment(payload="bad", charge_id="c")
    await successful_payment_handler(message, user_service, payment_service)
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
) -> None:
    """Reject when user is not found."""

    user_service = UserRoleService(user_repo=user_repo)
    payment_service = build_payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo, fake_tm, outbox_repo
    )

    message = FakeMessage(text=None, user=FakeUser(22, "adv", "Adv"), bot=FakeBot())
    message.successful_payment = FakeSuccessfulPayment(
        payload="00000000-0000-0000-0000-000000000600", charge_id="c"
    )
    await successful_payment_handler(message, user_service, payment_service)
    assert "Пользователь не найден" in message.answers[0]
