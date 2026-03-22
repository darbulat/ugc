"""Tests for admin write-to-user handlers (/write command)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from tests.helpers.fakes import (
    FakeFSMContext,
    FakeMessage,
    FakeMessengerClient,
    FakeUser,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.admin_message_to_user import (
    ACCESS_DENIED,
    CANCELLED,
    INVALID_UUID,
    PROMPT_TEXT,
    PROMPT_USER_ID,
    SENT_OK,
    USER_NOT_FOUND,
    USER_NOT_TELEGRAM,
    AdminWriteStates,
    cmd_cancel_write,
    cmd_write,
    step_text,
    step_user_id,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


@pytest.fixture
def user_repo() -> InMemoryUserRepository:
    """In-memory user repository for tests."""
    return InMemoryUserRepository()


@pytest.fixture
def user_role_service(user_repo: InMemoryUserRepository) -> UserRoleService:
    """User role service with in-memory repo."""
    return UserRoleService(user_repo=user_repo)


def _make_admin_user() -> User:
    """Create admin user entity (caller must save to repo)."""
    return User(
        user_id=uuid4(),
        telegram_id="100",
        messenger_type=MessengerType.TELEGRAM,
        username="admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=True,
    )


def _make_target_user() -> User:
    """Create target Telegram user entity (caller must save to repo)."""
    return User(
        user_id=uuid4(),
        telegram_id="200",
        messenger_type=MessengerType.TELEGRAM,
        username="target",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=False,
    )


@pytest.mark.asyncio
async def test_cmd_write_non_admin_access_denied(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Non-admin gets access denied and no state is set."""
    # No admin in repo
    message = FakeMessage(user=FakeUser(999, "user"))
    state = FakeFSMContext()

    await cmd_write(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == ACCESS_DENIED
    assert not state.cleared


@pytest.mark.asyncio
async def test_cmd_write_admin_asks_for_user_id(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Admin receives prompt to enter user ID."""
    admin = _make_admin_user()
    await user_repo.save(admin)
    message = FakeMessage(user=FakeUser(100, "admin"))
    state = FakeFSMContext()

    await cmd_write(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert len(messenger_client.sent_text) == 1
    assert PROMPT_USER_ID in messenger_client.sent_text[0]["text"]
    assert await state.get_state() == AdminWriteStates.waiting_user_id


@pytest.mark.asyncio
async def test_step_user_id_invalid_uuid(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Invalid UUID returns error message."""
    admin = _make_admin_user()
    await user_repo.save(admin)
    message = FakeMessage(text="not-a-uuid", user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_user_id)

    await step_user_id(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == INVALID_UUID


@pytest.mark.asyncio
async def test_step_user_id_user_not_found(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Non-existent user_id returns user not found."""
    admin = _make_admin_user()
    await user_repo.save(admin)
    unknown_id = uuid4()
    message = FakeMessage(text=str(unknown_id), user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_user_id)

    await step_user_id(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == USER_NOT_FOUND


@pytest.mark.asyncio
async def test_step_user_id_user_not_telegram_rejected(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Target user with non-Telegram messenger is rejected."""
    admin = _make_admin_user()
    await user_repo.save(admin)
    other_messenger = User(
        user_id=uuid4(),
        messenger_type=MessengerType.WHATSAPP,
        username="wa_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=False,
    )
    await user_repo.save(other_messenger)

    message = FakeMessage(
        text=str(other_messenger.user_id), user=FakeUser(100, "admin")
    )
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_user_id)

    await step_user_id(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == USER_NOT_TELEGRAM


@pytest.mark.asyncio
async def test_step_user_id_valid_then_ask_text(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Valid Telegram user ID leads to prompt for message text."""
    admin = _make_admin_user()
    target = _make_target_user()
    await user_repo.save(admin)
    await user_repo.save(target)
    message = FakeMessage(text=str(target.user_id), user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_user_id)

    await step_user_id(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == PROMPT_TEXT
    assert await state.get_state() == AdminWriteStates.waiting_text
    data = await state.get_data()
    assert data.get("target_user_id") == str(target.user_id)


@pytest.mark.asyncio
async def test_step_text_sends_to_target_and_confirms(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Message text is sent to target user and admin gets confirmation."""
    admin = _make_admin_user()
    target = _make_target_user()
    await user_repo.save(admin)
    await user_repo.save(target)
    message = FakeMessage(text="Hello from admin", user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_text)
    await state.update_data(target_user_id=str(target.user_id))

    await step_text(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    sent = messenger_client.sent_text
    assert len(sent) >= 2
    by_chat = {s["chat_id"]: s["text"] for s in sent}
    assert by_chat.get("200") == "Hello from admin"
    assert by_chat.get("100") == SENT_OK
    assert state.cleared


@pytest.mark.asyncio
async def test_step_text_empty_text_reprompts(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Empty message text reprompts for text."""
    admin = _make_admin_user()
    target = _make_target_user()
    await user_repo.save(admin)
    await user_repo.save(target)
    message = FakeMessage(text="   ", user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_text)
    await state.update_data(target_user_id=str(target.user_id))

    await step_text(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == PROMPT_TEXT
    assert not state.cleared


@pytest.mark.asyncio
async def test_cmd_cancel_write_clears_state(
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Cancel from waiting_user_id clears state and sends cancelled."""
    message = FakeMessage(user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_user_id)

    await cmd_cancel_write(
        message,
        state=state,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert state.cleared
    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == CANCELLED


@pytest.mark.asyncio
async def test_step_text_target_gone_clears_state(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """If target_user_id in state points to deleted user, clear and error."""
    admin = _make_admin_user()
    await user_repo.save(admin)
    message = FakeMessage(text="Hi", user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_text)
    await state.update_data(target_user_id=str(uuid4()))  # not in repo

    await step_text(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert state.cleared
    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == USER_NOT_FOUND


@pytest.mark.asyncio
async def test_cmd_write_non_admin_uses_message_answer_when_no_client(
    user_role_service: UserRoleService,
    event_adapter,
) -> None:
    """Without messenger_client, access denied is sent via message.answer."""
    message = FakeMessage(user=FakeUser(999, "user"))
    state = FakeFSMContext()

    await cmd_write(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=None,
        event_adapter=event_adapter,
    )

    assert len(message.answers) == 1
    assert message.answers[0] == ACCESS_DENIED


@pytest.mark.asyncio
async def test_step_text_send_failure_returns_error_to_admin(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    event_adapter,
) -> None:
    """Send to target raises; admin gets error, state not cleared."""
    admin = _make_admin_user()
    target = _make_target_user()
    await user_repo.save(admin)
    await user_repo.save(target)

    class FailingClient(FakeMessengerClient):
        """Fake client that fails when sending to target chat."""

        async def send_text(
            self,
            *,
            chat_id: str,
            text: str,
            keyboard: object | None = None,
            parse_mode: str | None = None,
            disable_preview: bool | None = None,
        ) -> None:
            if chat_id == target.telegram_id:
                raise RuntimeError("Telegram API error")
            await super().send_text(
                chat_id=chat_id,
                text=text,
                keyboard=keyboard,
                parse_mode=parse_mode,
                disable_preview=disable_preview,
            )

    messenger_client = FailingClient()
    message = FakeMessage(text="Hi", user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_text)
    await state.update_data(target_user_id=str(target.user_id))

    await step_text(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert not state.cleared
    sent = messenger_client.sent_text
    assert len(sent) == 1
    assert sent[0]["chat_id"] == "100"
    assert "Ошибка отправки" in sent[0]["text"]
    assert "Telegram API error" in sent[0]["text"]


@pytest.mark.asyncio
async def test_step_user_id_non_admin_access_denied(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """step_user_id from non-admin sends access denied."""
    target = _make_target_user()
    await user_repo.save(target)
    message = FakeMessage(
        text=str(target.user_id), user=FakeUser(999, "nonadmin")
    )
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_user_id)

    await step_user_id(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == ACCESS_DENIED


@pytest.mark.asyncio
async def test_step_text_non_admin_access_denied(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """step_text from non-admin sends access denied."""
    admin = _make_admin_user()
    target = _make_target_user()
    await user_repo.save(admin)
    await user_repo.save(target)
    message = FakeMessage(text="Hi", user=FakeUser(999, "nonadmin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_text)
    await state.update_data(target_user_id=str(target.user_id))

    await step_text(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == ACCESS_DENIED


@pytest.mark.asyncio
async def test_step_text_invalid_uuid_in_state_clears_and_errors(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Invalid UUID in state data clears state and sends user not found."""
    admin = _make_admin_user()
    await user_repo.save(admin)
    message = FakeMessage(text="Hi", user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_text)
    await state.update_data(target_user_id="not-a-valid-uuid")

    await step_text(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert state.cleared
    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == USER_NOT_FOUND


@pytest.mark.asyncio
async def test_step_text_no_target_user_id_in_state(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Empty state data clears state and sends user not found."""
    admin = _make_admin_user()
    await user_repo.save(admin)
    message = FakeMessage(text="Hi", user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_text)
    await state.set_data({})

    await step_text(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert state.cleared
    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == USER_NOT_FOUND


@pytest.mark.asyncio
async def test_require_admin_without_messenger_client_uses_message_answer(
    user_role_service: UserRoleService,
    event_adapter,
) -> None:
    """_require_admin with no client falls back to message.answer."""
    from ugc_bot.bot.handlers.admin_message_to_user import _require_admin

    message = FakeMessage(user=FakeUser(999, "nonadmin"))
    result = await _require_admin(
        message, event_adapter, user_role_service, None
    )
    assert result is False
    assert len(message.answers) == 1


@pytest.mark.asyncio
async def test_step_user_id_empty_text_is_invalid(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Empty message text is treated as invalid UUID."""
    admin = _make_admin_user()
    await user_repo.save(admin)
    message = FakeMessage(text="", user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_user_id)

    await step_user_id(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == INVALID_UUID


@pytest.mark.asyncio
async def test_step_user_id_short_text_without_dash_is_invalid(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """Short text without dash is treated as invalid UUID."""
    admin = _make_admin_user()
    await user_repo.save(admin)
    message = FakeMessage(text="abc", user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_user_id)

    await step_user_id(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == INVALID_UUID


@pytest.mark.asyncio
async def test_step_text_target_without_telegram_id(
    user_repo: InMemoryUserRepository,
    user_role_service: UserRoleService,
    messenger_client: FakeMessengerClient,
    event_adapter,
) -> None:
    """step_text clears state when target has no telegram_id."""
    from datetime import datetime, timezone
    from uuid import uuid4

    admin = _make_admin_user()
    no_tg_user = User(
        user_id=uuid4(),
        messenger_type=MessengerType.WHATSAPP,
        username="wa_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        admin=False,
    )
    await user_repo.save(admin)
    await user_repo.save(no_tg_user)

    message = FakeMessage(text="Hello", user=FakeUser(100, "admin"))
    state = FakeFSMContext()
    await state.set_state(AdminWriteStates.waiting_text)
    await state.update_data(target_user_id=str(no_tg_user.user_id))

    await step_text(
        message,
        state=state,
        user_role_service=user_role_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert state.cleared
    assert len(messenger_client.sent_text) == 1
    assert messenger_client.sent_text[0]["text"] == USER_NOT_TELEGRAM
