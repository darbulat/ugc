"""Tests for admin notification service."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_complaint,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import Complaint, User
from ugc_bot.domain.enums import ComplaintStatus, MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


class FakeBot:
    """Bot stub that captures send_message and send_photo calls."""

    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.photos: list[tuple[int, str, str | None]] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        **kwargs: object,
    ) -> None:
        self.messages.append((chat_id, text))

    async def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: str | None = None,
        parse_mode: str | None = None,
        **kwargs: object,
    ) -> None:
        self.photos.append((chat_id, photo, caption))


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
    chat_id, text = bot.messages[0]
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
    chat_id, photo1, caption = bot.photos[0]
    assert chat_id == 999
    assert photo1 == "photo1"
    assert caption is not None
    assert "Новая жалоба" in caption
    assert "3 шт" in caption
    assert bot.photos[1] == (999, "photo2", None)
    assert bot.photos[2] == (999, "photo3", None)


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
    _, text = bot.messages[0]
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
