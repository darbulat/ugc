"""Tests for order creation handlers."""

import pytest

from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.contact_pricing_service import ContactPricingService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.order_creation import (
    handle_barter_choice,
    handle_barter_description,
    handle_bloggers_needed,
    handle_offer_text,
    handle_price,
    handle_product_link,
    handle_ugc_requirements,
    start_order_creation,
)
from datetime import datetime, timezone
from uuid import UUID

from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import AdvertiserProfile, ContactPricing, Order, User
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryContactPricingRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)


class FakeUser:
    """Minimal user stub."""

    def __init__(self, user_id: int, username: str | None, first_name: str) -> None:
        self.id = user_id
        self.username = username
        self.first_name = first_name


class FakeBot:
    """Minimal bot stub for invoices."""

    def __init__(self) -> None:
        self.invoices: list[dict] = []

    async def send_invoice(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.invoices.append(kwargs)


class FakeMessage:
    """Minimal message stub for handler tests."""

    def __init__(
        self, text: str | None, user: FakeUser | None, bot: FakeBot | None = None
    ) -> None:
        self.text = text
        self.from_user = user
        self.answers: list[str] = []
        self.bot = bot
        self.chat = type("Chat", (), {"id": user.id if user else 0})()

    async def answer(self, text: str, reply_markup=None, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """Capture response text."""

        self.answers.append(text)


class FakeFSMContext:
    """Minimal FSM context for tests."""

    def __init__(self) -> None:
        self._data: dict = {}
        self.state = None

    async def update_data(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._data.update(kwargs)

    async def set_state(self, state) -> None:  # type: ignore[no-untyped-def]
        self.state = state

    async def get_data(self) -> dict:  # type: ignore[no-untyped-def]
        return dict(self._data)

    async def clear(self) -> None:
        self._data.clear()
        self.state = None


def _profile_service(
    user_repo: InMemoryUserRepository,
    advertiser_repo: InMemoryAdvertiserProfileRepository,
) -> ProfileService:
    """Build profile service for tests."""

    return ProfileService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        advertiser_repo=advertiser_repo,
    )


def _add_advertiser_profile(
    advertiser_repo: InMemoryAdvertiserProfileRepository, user_id: UUID
) -> None:
    """Seed advertiser profile."""

    advertiser_repo.save(AdvertiserProfile(user_id=user_id, contact="contact"))


def _pricing_service(prices: dict[int, float]) -> ContactPricingService:
    """Build contact pricing service."""

    repo = InMemoryContactPricingRepository()
    for count, price in prices.items():
        repo.save(
            ContactPricing(
                bloggers_count=count,
                price=price,
                updated_at=datetime.now(timezone.utc),
            )
        )
    return ContactPricingService(pricing_repo=repo)


@pytest.mark.asyncio
async def test_start_order_creation_requires_role() -> None:
    """Require advertiser role before creation."""

    repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_service = UserRoleService(user_repo=repo)
    order_service = OrderService(
        user_repo=repo,
        advertiser_repo=advertiser_repo,
        order_repo=InMemoryOrderRepository(),
    )
    profile_service = _profile_service(repo, advertiser_repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await start_order_creation(
        message, state, user_service, profile_service, order_service
    )
    assert "Пользователь не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_order_creation_flow_new_advertiser() -> None:
    """New advertisers skip barter step."""

    repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=repo)
    order_service = OrderService(
        user_repo=repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )
    user = user_service.set_user(
        external_id="5",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    _add_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = _profile_service(repo, advertiser_repo)

    message = FakeMessage(text=None, user=FakeUser(5, "adv", "Adv"))
    state = FakeFSMContext()
    await start_order_creation(
        message, state, user_service, profile_service, order_service
    )
    assert state._data["is_new"] is True

    await handle_product_link(FakeMessage(text="https://example.com", user=None), state)
    await handle_offer_text(FakeMessage(text="Offer", user=None), state)
    await handle_ugc_requirements(FakeMessage(text="пропустить", user=None), state)
    await handle_price(FakeMessage(text="1000", user=None), state)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = _pricing_service({3: 1500.0})
    await handle_bloggers_needed(
        FakeMessage(text="3", user=FakeUser(5, "adv", "Adv"), bot=bot),
        state,
        order_service,
        config,
        pricing_service,
    )
    assert bot.invoices

    assert len(order_repo.orders) == 1


@pytest.mark.asyncio
async def test_order_creation_flow_with_barter() -> None:
    """Handle barter flow for existing advertisers."""

    repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=repo)
    order_service = OrderService(
        user_repo=repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )
    user = user_service.set_user(
        external_id="6",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    _add_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = _profile_service(repo, advertiser_repo)
    order_repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000801"),
            advertiser_id=user.user_id,
            product_link="https://example.com",
            offer_text="Old",
            ugc_requirements=None,
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,
            created_at=datetime.now(timezone.utc),
            contacts_sent_at=None,
        )
    )

    message = FakeMessage(text=None, user=FakeUser(6, "adv", "Adv"))
    state = FakeFSMContext()
    await start_order_creation(
        message, state, user_service, profile_service, order_service
    )

    await handle_product_link(FakeMessage(text="https://example.com", user=None), state)
    await handle_offer_text(FakeMessage(text="Offer", user=None), state)
    await handle_ugc_requirements(FakeMessage(text="пропустить", user=None), state)
    await handle_barter_choice(FakeMessage(text="Да", user=None), state)
    await handle_barter_description(FakeMessage(text="Barter", user=None), state)
    await handle_price(FakeMessage(text="1500", user=None), state)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    bot = FakeBot()
    pricing_service = _pricing_service({20: 5000.0})
    await handle_bloggers_needed(
        FakeMessage(text="20", user=FakeUser(6, "adv", "Adv"), bot=bot),
        state,
        order_service,
        config,
        pricing_service,
    )
    assert bot.invoices

    assert len(order_repo.orders) == 2


@pytest.mark.asyncio
async def test_start_order_creation_blocked_user() -> None:
    """Block order creation for blocked users."""

    repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_service = OrderService(
        user_repo=repo,
        advertiser_repo=advertiser_repo,
        order_repo=InMemoryOrderRepository(),
    )
    profile_service = _profile_service(repo, advertiser_repo)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000701"),
        external_id="7",
        messenger_type=MessengerType.TELEGRAM,
        username="blocked",
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo.save(user)
    user_service = UserRoleService(user_repo=repo)

    message = FakeMessage(text=None, user=FakeUser(7, "blocked", "Blocked"))
    state = FakeFSMContext()

    await start_order_creation(
        message, state, user_service, profile_service, order_service
    )

    assert "Заблокированные" in message.answers[0]


@pytest.mark.asyncio
async def test_bloggers_needed_limit_for_new_advertiser() -> None:
    """Reject invalid bloggers count for NEW advertisers."""

    repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_service = OrderService(
        user_repo=repo,
        advertiser_repo=advertiser_repo,
        order_repo=InMemoryOrderRepository(),
    )
    state = FakeFSMContext()
    await state.update_data(is_new=True)

    message = FakeMessage(text="20", user=None)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )
    pricing_service = _pricing_service({20: 5000.0})
    await handle_bloggers_needed(message, state, order_service, config, pricing_service)

    assert "NEW рекламодатели" in message.answers[0]
