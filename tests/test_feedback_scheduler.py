"""Tests for feedback scheduler."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import (
    AdvertiserProfile,
    Interaction,
    Order,
    OrderResponse,
    User,
)
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    OrderStatus,
    UserStatus,
)
from ugc_bot.feedback_scheduler import _feedback_keyboard, main, run_loop, run_once
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryInteractionRepository,
    InMemoryOrderRepository,
    InMemoryOrderResponseRepository,
    InMemoryUserRepository,
)


class FakeBot:
    """Capture sent messages."""

    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        self.messages.append((chat_id, text))


class FakeSession:
    """Minimal async session."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeBotWithSession(FakeBot):
    """Fake bot with session."""

    def __init__(self) -> None:
        super().__init__()
        self.session = FakeSession()


def test_feedback_keyboard() -> None:
    """Ensure feedback keyboard contains callback data."""

    markup = _feedback_keyboard("adv", UUID("00000000-0000-0000-0000-000000000950"))
    first = markup.inline_keyboard[0][0]
    assert "feedback:adv:" in first.callback_data


@pytest.mark.asyncio
async def test_run_once_sends_feedback_requests() -> None:
    """Send feedback to advertiser and blogger."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000960"),
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000961"),
        external_id="11",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(advertiser)
    user_repo.save(blogger)
    advertiser_repo.save(
        AdvertiserProfile(
            user_id=advertiser.user_id, contact="c", instagram_url=None, confirmed=False
        )
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000962"),
        advertiser_id=advertiser.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    order_repo.save(order)
    response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000963"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
    )

    # Create interaction with next_check_at in the past
    interaction = interaction_service.create_for_contacts_sent(
        order_id=order.order_id,
        blogger_id=blogger.user_id,
        advertiser_id=advertiser.user_id,
    )
    # Manually set next_check_at to past
    past_interaction = Interaction(
        interaction_id=interaction.interaction_id,
        order_id=interaction.order_id,
        blogger_id=interaction.blogger_id,
        advertiser_id=interaction.advertiser_id,
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=datetime.now(timezone.utc) - timedelta(hours=1),
        created_at=interaction.created_at,
        updated_at=interaction.updated_at,
    )
    interaction_repo.save(past_interaction)

    bot = FakeBot()
    await run_once(
        bot,
        interaction_repo,
        interaction_service,
        user_service,
        cutoff=datetime.now(timezone.utc),
    )
    assert len(bot.messages) == 2


@pytest.mark.asyncio
async def test_run_once_skips_active_orders() -> None:
    """Skip interactions that are not PENDING or have future next_check_at."""

    interaction_repo = InMemoryInteractionRepository()
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    # Create interaction with future next_check_at (should be skipped)
    interaction_repo.save(
        Interaction(
            interaction_id=UUID("00000000-0000-0000-0000-000000000970"),
            order_id=UUID("00000000-0000-0000-0000-000000000971"),
            blogger_id=UUID("00000000-0000-0000-0000-000000000972"),
            advertiser_id=UUID("00000000-0000-0000-0000-000000000973"),
            status=InteractionStatus.PENDING,
            from_advertiser=None,
            from_blogger=None,
            postpone_count=0,
            next_check_at=datetime.now(timezone.utc) + timedelta(hours=1),  # Future
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    bot = FakeBot()
    await run_once(
        bot,
        interaction_repo,
        interaction_service,
        user_service,
        cutoff=datetime.now(timezone.utc),
    )
    assert not bot.messages


@pytest.mark.asyncio
async def test_run_once_skips_orders_without_responses() -> None:
    """Skip when no interactions are due for feedback."""

    interaction_repo = InMemoryInteractionRepository()
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    # No interactions created, so nothing to process
    bot = FakeBot()
    await run_once(
        bot,
        interaction_repo,
        interaction_service,
        user_service,
        cutoff=datetime.now(timezone.utc),
    )
    assert not bot.messages


@pytest.mark.asyncio
async def test_run_once_existing_feedback_no_messages() -> None:
    """Skip sending when feedback already collected."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000980"),
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000981"),
        external_id="21",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(advertiser)
    user_repo.save(blogger)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000982"),
        advertiser_id=advertiser.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=datetime.now(timezone.utc) - timedelta(hours=73),
    )
    order_repo.save(order)
    response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000983"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
    )
    interaction_repo.save(
        Interaction(
            interaction_id=UUID("00000000-0000-0000-0000-000000000984"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            advertiser_id=advertiser.user_id,
            status=InteractionStatus.OK,
            from_advertiser="✅ Сделка состоялась",
            from_blogger="✅ Всё прошло нормально",
            postpone_count=0,
            next_check_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    bot = FakeBot()
    await run_once(
        bot,
        interaction_repo,
        interaction_service,
        user_service,
        cutoff=datetime.now(timezone.utc),
    )
    assert not bot.messages


@pytest.mark.asyncio
async def test_run_loop_closes_session() -> None:
    """Ensure run_loop closes bot session."""

    bot = FakeBotWithSession()
    interaction_repo = InMemoryInteractionRepository()
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    await run_loop(
        bot,
        interaction_repo,
        interaction_service,
        user_service,
        interval_seconds=0,
        max_iterations=1,
    )
    assert bot.session.closed is True


@pytest.mark.asyncio
async def test_run_loop_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure run_loop awaits sleep between iterations."""

    slept = {"called": False}

    async def _fake_sleep(_: int) -> None:
        slept["called"] = True

    monkeypatch.setattr("ugc_bot.feedback_scheduler.asyncio.sleep", _fake_sleep)

    bot = FakeBotWithSession()
    interaction_repo = InMemoryInteractionRepository()
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    await run_loop(
        bot,
        interaction_repo,
        interaction_service,
        user_service,
        interval_seconds=1,
        max_iterations=2,
    )
    assert slept["called"] is True


def test_main_feedback_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Main exits when feedback disabled."""

    monkeypatch.setenv("FEEDBACK_ENABLED", "false")
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    main()


def test_main_feedback_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Main runs asyncio loop when feedback enabled."""

    monkeypatch.setenv("FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("BOT_TOKEN", "123456:ABCDEF1234567890abcdef1234567890")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
    monkeypatch.setattr(
        "ugc_bot.feedback_scheduler.create_session_factory", lambda _: object()
    )

    def _run(coro) -> None:  # type: ignore[no-untyped-def]
        coro.close()

    monkeypatch.setattr("ugc_bot.feedback_scheduler.asyncio.run", _run)
    main()
