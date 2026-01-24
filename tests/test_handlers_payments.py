"""Tests for payment handlers."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.contact_pricing_service import ContactPricingService
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.payments import (
    pay_order,
    pre_checkout_query_handler,
    successful_payment_handler,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import AdvertiserProfile, ContactPricing, Order, User
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryContactPricingRepository,
    InMemoryOrderRepository,
    InMemoryOutboxRepository,
    InMemoryPaymentRepository,
    InMemoryUserRepository,
    NoopOfferBroadcaster,
)


class FakeUser:
    """Minimal user stub."""

    def __init__(self, user_id: int, username: str | None, first_name: str) -> None:
        self.id = user_id
        self.username = username
        self.first_name = first_name


class FakeBot:
    """Minimal bot stub."""

    def __init__(self) -> None:
        self.invoices: list[dict] = []
        self.pre_checkout_answers: list[dict] = []

    async def send_invoice(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.invoices.append(kwargs)

    async def answer_pre_checkout_query(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.pre_checkout_answers.append(kwargs)


class FakeMessage:
    """Minimal message stub for handler tests."""

    def __init__(self, text: str | None, user: FakeUser | None, bot) -> None:
        self.text = text
        self.from_user = user
        self.bot = bot
        self.answers: list[str] = []
        self.chat = type("Chat", (), {"id": user.id if user else 0})()
        self.successful_payment = None

    async def answer(self, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        self.answers.append(text)


class FakePreCheckoutQuery:
    """Minimal pre-checkout query stub."""

    def __init__(self, query_id: str, bot) -> None:
        self.id = query_id
        self.bot = bot


class FakeSuccessfulPayment:
    """Minimal successful payment stub."""

    def __init__(self, payload: str, charge_id: str) -> None:
        self.invoice_payload = payload
        self.provider_payment_charge_id = charge_id
        self.total_amount = 100000
        self.currency = "RUB"


def _seed_user(
    user_repo: InMemoryUserRepository, user_id: UUID, external_id: str
) -> User:
    """Seed user with advertiser profile."""

    user = User(
        user_id=user_id,
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    return user


class FakeConfig(AppConfig):
    """Config stub with provider token."""


def _profile_service(
    user_repo: InMemoryUserRepository,
    advertiser_repo: InMemoryAdvertiserProfileRepository,
) -> ProfileService:
    """Create profile service for handler tests."""

    return ProfileService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        advertiser_repo=advertiser_repo,
    )


def _contact_pricing_service() -> ContactPricingService:
    """Create contact pricing service for handler tests."""

    return ContactPricingService(
        pricing_repo=InMemoryContactPricingRepository(),
    )


def _add_advertiser_profile(
    advertiser_repo: InMemoryAdvertiserProfileRepository, user_id: UUID
) -> None:
    """Seed advertiser profile."""

    advertiser_repo.save(
        AdvertiserProfile(
            user_id=user_id, contact="contact", instagram_url=None, confirmed=False
        )
    )


def _payment_service(
    user_repo: InMemoryUserRepository,
    advertiser_repo: InMemoryAdvertiserProfileRepository,
    order_repo: InMemoryOrderRepository,
    payment_repo: InMemoryPaymentRepository,
) -> PaymentService:
    """Create payment service for tests."""

    outbox_repo = InMemoryOutboxRepository()
    outbox_publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)

    return PaymentService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=NoopOfferBroadcaster(),
        outbox_publisher=outbox_publisher,
    )


@pytest.mark.asyncio
async def test_pay_order_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invoice is sent when order is valid."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )
    profile_service = _profile_service(user_repo, advertiser_repo)
    contact_pricing_service = _contact_pricing_service()

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000500"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    _add_advertiser_profile(advertiser_repo, user.user_id)
    user_service.set_user(
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000501"),
        advertiser_id=user.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

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
async def test_pay_order_missing_provider_token() -> None:
    """Reject when provider token missing."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )
    profile_service = _profile_service(user_repo, advertiser_repo)
    contact_pricing_service = _contact_pricing_service()

    # Override price for 3 bloggers to be positive so provider check is needed
    contact_pricing_service.pricing_repo.save(
        ContactPricing(
            bloggers_count=3, price=100.0, updated_at=datetime.now(timezone.utc)
        )
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000502"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    _add_advertiser_profile(advertiser_repo, user.user_id)
    user_service.set_user(
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    order_repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000503"),
            advertiser_id=user.user_id,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            contacts_sent_at=None,
        )
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
async def test_pay_order_invalid_args() -> None:
    """Reject missing order id argument."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )
    profile_service = _profile_service(user_repo, advertiser_repo)
    contact_pricing_service = _contact_pricing_service()

    user = _seed_user(user_repo, UUID("00000000-0000-0000-0000-000000000510"), "10")
    _add_advertiser_profile(advertiser_repo, user.user_id)
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
async def test_pay_order_invalid_uuid() -> None:
    """Reject invalid order id format."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )
    profile_service = _profile_service(user_repo, advertiser_repo)
    contact_pricing_service = _contact_pricing_service()

    user = _seed_user(user_repo, UUID("00000000-0000-0000-0000-000000000511"), "11")
    _add_advertiser_profile(advertiser_repo, user.user_id)
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
async def test_pay_order_order_not_found() -> None:
    """Reject missing order."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )
    profile_service = _profile_service(user_repo, advertiser_repo)
    contact_pricing_service = _contact_pricing_service()

    user = _seed_user(user_repo, UUID("00000000-0000-0000-0000-000000000512"), "12")
    _add_advertiser_profile(advertiser_repo, user.user_id)
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
async def test_pay_order_wrong_owner() -> None:
    """Reject payments for чужие заказы."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )
    profile_service = _profile_service(user_repo, advertiser_repo)
    contact_pricing_service = _contact_pricing_service()

    user = _seed_user(user_repo, UUID("00000000-0000-0000-0000-000000000513"), "13")
    other = _seed_user(user_repo, UUID("00000000-0000-0000-0000-000000000514"), "14")
    _add_advertiser_profile(advertiser_repo, user.user_id)

    order_repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000515"),
            advertiser_id=other.user_id,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            contacts_sent_at=None,
        )
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
async def test_pay_order_not_new_status() -> None:
    """Reject payments for non-NEW orders."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )
    profile_service = _profile_service(user_repo, advertiser_repo)
    contact_pricing_service = _contact_pricing_service()

    user = _seed_user(user_repo, UUID("00000000-0000-0000-0000-000000000516"), "15")
    _add_advertiser_profile(advertiser_repo, user.user_id)
    order_repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000517"),
            advertiser_id=user.user_id,
            product_link="https://example.com",
            offer_text="Offer",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
            contacts_sent_at=None,
        )
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
async def test_pay_order_blocked_user() -> None:
    """Reject blocked users."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )
    profile_service = _profile_service(user_repo, advertiser_repo)
    contact_pricing_service = _contact_pricing_service()

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000518"),
        external_id="16",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
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
async def test_pay_order_paused_user() -> None:
    """Reject paused users."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )
    profile_service = _profile_service(user_repo, advertiser_repo)
    contact_pricing_service = _contact_pricing_service()

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000519"),
        external_id="17",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.PAUSE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
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
async def test_pay_order_missing_profile() -> None:
    """Reject missing advertiser profile."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )
    profile_service = _profile_service(user_repo, advertiser_repo)
    contact_pricing_service = _contact_pricing_service()

    _seed_user(user_repo, UUID("00000000-0000-0000-0000-000000000521"), "21")
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
async def test_pre_checkout_query_ok() -> None:
    """Confirm pre-checkout query."""

    bot = FakeBot()
    query = FakePreCheckoutQuery("q1", bot)
    await pre_checkout_query_handler(query)
    assert bot.pre_checkout_answers


@pytest.mark.asyncio
async def test_pre_checkout_query_without_bot() -> None:
    """Skip when bot is missing."""

    query = FakePreCheckoutQuery("q1", None)
    await pre_checkout_query_handler(query)


@pytest.mark.asyncio
async def test_successful_payment_handler() -> None:
    """Confirm payment on successful payment message."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000504"),
        external_id="3",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    _add_advertiser_profile(advertiser_repo, user.user_id)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000505"),
        advertiser_id=user.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

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
    assert order_repo.get_by_id(order.order_id).status == OrderStatus.NEW

    # Process outbox events to activate order
    from ugc_bot.infrastructure.kafka.publisher import NoopOrderActivationPublisher

    kafka_publisher = NoopOrderActivationPublisher()
    payment_service.outbox_publisher.process_pending_events(
        kafka_publisher, max_retries=3
    )

    # Now order should be activated
    assert order_repo.get_by_id(order.order_id).status == OrderStatus.ACTIVE


@pytest.mark.asyncio
async def test_successful_payment_invalid_payload() -> None:
    """Reject invalid payload."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    payment_repo = InMemoryPaymentRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )
    user = _seed_user(user_repo, UUID("00000000-0000-0000-0000-000000000520"), "20")
    _add_advertiser_profile(advertiser_repo, user.user_id)

    message = FakeMessage(text=None, user=FakeUser(20, "adv", "Adv"), bot=FakeBot())
    message.successful_payment = FakeSuccessfulPayment(payload="bad", charge_id="c")
    await successful_payment_handler(message, user_service, payment_service)
    assert "Не удалось определить заказ" in message.answers[0]


@pytest.mark.asyncio
async def test_successful_payment_user_not_found() -> None:
    """Reject when user is not found."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    payment_repo = InMemoryPaymentRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = _payment_service(
        user_repo, advertiser_repo, order_repo, payment_repo
    )

    message = FakeMessage(text=None, user=FakeUser(22, "adv", "Adv"), bot=FakeBot())
    message.successful_payment = FakeSuccessfulPayment(
        payload="00000000-0000-0000-0000-000000000600", charge_id="c"
    )
    await successful_payment_handler(message, user_service, payment_service)
    assert "Пользователь не найден" in message.answers[0]
