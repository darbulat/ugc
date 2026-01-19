"""Tests for feedback handler."""

import pytest
from uuid import UUID
from datetime import datetime, timezone

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.feedback import handle_feedback
from ugc_bot.domain.entities import Interaction, User
from ugc_bot.domain.enums import InteractionStatus, MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInteractionRepository,
    InMemoryUserRepository,
)


class FakeUser:
    """Minimal user stub."""

    def __init__(self, user_id: int) -> None:
        self.id = user_id


class FakeCallback:
    """Minimal callback stub."""

    def __init__(self, data: str, user: FakeUser) -> None:
        self.data = data
        self.from_user = user
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        """Capture callback answer."""

        self.answers.append(text)


@pytest.mark.asyncio
async def test_feedback_handler_advertiser_ok() -> None:
    """Advertiser feedback updates interaction."""

    user_repo = InMemoryUserRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000930"),
        external_id="42",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(advertiser)

    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000931"),
        order_id=UUID("00000000-0000-0000-0000-000000000932"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000933"),
        advertiser_id=advertiser.user_id,
        status=InteractionStatus.NO_DEAL,
        from_advertiser=None,
        from_blogger=None,
        created_at=datetime.now(timezone.utc),
    )
    interaction_repo.save(interaction)

    callback = FakeCallback(
        data=f"feedback:adv:{interaction.interaction_id}:ok", user=FakeUser(42)
    )
    await handle_feedback(callback, user_service, interaction_service)

    assert callback.answers
    updated = interaction_repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert updated.from_advertiser == InteractionStatus.OK.value


@pytest.mark.asyncio
async def test_feedback_handler_wrong_user() -> None:
    """Reject feedback from unrelated user."""

    user_repo = InMemoryUserRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000940"),
        external_id="100",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    other_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000944"),
        external_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="other",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(advertiser)
    user_repo.save(other_user)
    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000941"),
        order_id=UUID("00000000-0000-0000-0000-000000000942"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000943"),
        advertiser_id=advertiser.user_id,
        status=InteractionStatus.NO_DEAL,
        from_advertiser=None,
        from_blogger=None,
        created_at=datetime.now(timezone.utc),
    )
    interaction_repo.save(interaction)

    callback = FakeCallback(
        data=f"feedback:adv:{interaction.interaction_id}:ok", user=FakeUser(999)
    )
    await handle_feedback(callback, user_service, interaction_service)
    assert "Недостаточно прав." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_invalid_format() -> None:
    """Reject malformed callback data."""

    user_repo = InMemoryUserRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(data="feedback:bad", user=FakeUser(1))
    await handle_feedback(callback, user_service, interaction_service)
    assert "Неверный формат ответа." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_invalid_status() -> None:
    """Reject unknown status values."""

    user_repo = InMemoryUserRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(
        data="feedback:adv:00000000-0000-0000-0000-000000000999:bad", user=FakeUser(1)
    )
    await handle_feedback(callback, user_service, interaction_service)
    assert "Неверный статус." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_invalid_uuid() -> None:
    """Reject invalid UUID values."""

    user_repo = InMemoryUserRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(data="feedback:adv:not-a-uuid:ok", user=FakeUser(1))
    await handle_feedback(callback, user_service, interaction_service)
    assert "Неверный идентификатор." in callback.answers


@pytest.mark.asyncio
async def test_feedback_handler_user_not_found() -> None:
    """Reject when user is missing."""

    user_repo = InMemoryUserRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    callback = FakeCallback(
        data="feedback:adv:00000000-0000-0000-0000-000000001000:ok",
        user=FakeUser(123),
    )
    await handle_feedback(callback, user_service, interaction_service)
    assert "Пользователь не найден." in callback.answers
