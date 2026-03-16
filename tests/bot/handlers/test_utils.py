"""Tests for handler utilities."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from tests.helpers.fakes import FakeMessengerClient
from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.bot.handlers.utils import (
    LegacyMessengerClient,
    RateLimiter,
    _answer_callback_or_fallback,
    _resolve_user_lookup_from_callback,
    _resolve_user_lookup_from_message,
    _send_text_or_answer,
    format_agreements_message,
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
    parse_user_id_from_state,
    send_with_retry,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus


def test_rate_limiter_allows_within_limit() -> None:
    """Allow requests within the limit."""

    limiter = RateLimiter(limit=2, window_seconds=10.0)
    assert limiter.allow("key") is True
    assert limiter.allow("key") is True
    assert limiter.allow("key") is False


@pytest.mark.asyncio
async def test_send_with_retry_success() -> None:
    """Return True on successful send."""

    messenger_client = FakeMessengerClient()
    ok = await send_with_retry(
        messenger_client,
        chat_id="1",
        text="hi",
        retries=2,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
    )
    assert ok is True
    assert len(messenger_client.sent_text) == 1


@pytest.mark.asyncio
async def test_send_with_retry_failure() -> None:
    """Return False after retries exhausted."""

    class FailingMessenger:
        async def send_text(self, *, chat_id: str, text: str, **kwargs) -> None:
            raise RuntimeError("fail")

    ok = await send_with_retry(
        FailingMessenger(),
        chat_id="1",
        text="hi",
        retries=2,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
    )
    assert ok is False


@pytest.mark.asyncio
async def test_send_with_retry_user_blocked_bot_no_retry() -> None:
    """When user blocked the bot, return False immediately without retry."""
    blocked_error = TelegramForbiddenError(
        message="Forbidden: bot was blocked by the user",
        method=SendMessage(chat_id=0, text=""),
    )
    call_count = 0

    class BlockedUserMessenger:
        async def send_text(self, *, chat_id: str, text: str, **kwargs) -> None:
            nonlocal call_count
            call_count += 1
            raise blocked_error

    ok = await send_with_retry(
        BlockedUserMessenger(),
        chat_id="1",
        text="hi",
        retries=3,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
    )
    assert ok is False
    assert call_count == 1


def test_parse_user_id_from_state_missing() -> None:
    """Return None when key is missing."""
    assert parse_user_id_from_state({}, key="user_id") is None
    assert parse_user_id_from_state({"other": "x"}, key="user_id") is None


def test_parse_user_id_from_state_from_string() -> None:
    """Parse UUID from string value."""
    uid = uuid4()
    assert parse_user_id_from_state({"user_id": str(uid)}) == uid


def test_parse_user_id_from_state_already_uuid() -> None:
    """Return UUID when value is already UUID."""
    uid = uuid4()
    assert parse_user_id_from_state({"user_id": uid}) == uid


def test_parse_user_id_from_state_custom_key() -> None:
    """Use custom key (e.g. edit_user_id)."""
    uid = uuid4()
    assert (
        parse_user_id_from_state({"edit_user_id": str(uid)}, key="edit_user_id")
        == uid
    )


def test_parse_user_id_from_state_invalid_string() -> None:
    """Return None for invalid UUID string."""
    assert parse_user_id_from_state({"user_id": "not-a-uuid"}) is None


def test_parse_user_id_from_state_invalid_type() -> None:
    """Return None when value is not str or UUID (e.g. int, list)."""
    assert parse_user_id_from_state({"user_id": 123}) is None
    assert parse_user_id_from_state({"user_id": []}) is None


def test_resolve_user_lookup_from_message_fallback() -> None:
    """Fallback uses from_user and answer when message is not DTO."""

    class DummyMessage:
        def __init__(self) -> None:
            self.from_user = type("U", (), {"id": 42})()

        async def answer(self, text: str, **kwargs) -> None:
            _ = text, kwargs

    dummy = DummyMessage()
    (
        external_id,
        messenger_type,
        chat_id,
        answer,
        client,
        service,
    ) = _resolve_user_lookup_from_message(dummy, "svc", None)
    assert external_id == "42"
    assert chat_id == "42"
    assert messenger_type == MessengerType.TELEGRAM
    assert callable(answer)
    assert client is None
    assert service == "svc"


def test_resolve_user_lookup_from_callback_fallback() -> None:
    """Fallback uses from_user and answer when callback is not DTO."""

    class DummyCallback:
        def __init__(self) -> None:
            self.from_user = type("U", (), {"id": 7})()

        async def answer(self, text: str, **kwargs) -> None:
            _ = text, kwargs

    dummy = DummyCallback()
    (
        external_id,
        messenger_type,
        callback_id,
        answer,
        client,
        service,
    ) = _resolve_user_lookup_from_callback(dummy, "svc", None)
    assert external_id == "7"
    assert callback_id == ""
    assert messenger_type == MessengerType.TELEGRAM
    assert callable(answer)
    assert client is None
    assert service == "svc"


@pytest.mark.asyncio
async def test_send_text_or_answer_fallback_text_only() -> None:
    """Fallback sends text via answer when client missing."""
    calls: list[str] = []

    async def answer(text: str) -> None:
        calls.append(text)

    await _send_text_or_answer(
        None,
        chat_id="1",
        text="hello",
        answer=answer,
        keyboard=None,
    )
    assert calls == ["hello"]


@pytest.mark.asyncio
async def test_get_user_and_ensure_allowed_none() -> None:
    """When user is None, send user_not_found_msg and return None."""

    class NoUserService:
        async def get_user(
            self, external_id: str, messenger_type: object
        ) -> None:
            return None

    messenger_client = FakeMessengerClient()
    message = IncomingMessage(
        chat_id="123",
        user=IncomingUser(
            external_id="123",
            messenger_type=MessengerType.TELEGRAM,
        ),
        text="hi",
    )
    result = await get_user_and_ensure_allowed(
        message,
        messenger_client,
        NoUserService(),
        user_not_found_msg="Not found",
        blocked_msg="Blocked",
        pause_msg="Pause",
    )
    assert result is None
    assert messenger_client.sent_text[0]["text"] == "Not found"


@pytest.mark.asyncio
async def test_get_user_and_ensure_allowed_blocked() -> None:
    """When user is BLOCKED, send blocked_msg and return None."""

    blocked_user = User(
        user_id=uuid4(),
        external_id="456",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )

    class BlockedUserService:
        async def get_user(
            self, external_id: str, messenger_type: object
        ) -> User | None:
            return blocked_user

    messenger_client = FakeMessengerClient()
    message = IncomingMessage(
        chat_id="456",
        user=IncomingUser(
            external_id="456",
            messenger_type=MessengerType.TELEGRAM,
        ),
        text="hi",
    )
    result = await get_user_and_ensure_allowed(
        message,
        messenger_client,
        BlockedUserService(),
        user_not_found_msg="Not found",
        blocked_msg="Blocked",
        pause_msg="Pause",
    )
    assert result is None
    assert messenger_client.sent_text[0]["text"] == "Blocked"


@pytest.mark.asyncio
async def test_get_user_and_ensure_allowed_ok() -> None:
    """When user is allowed, return user."""

    ok_user = User(
        user_id=uuid4(),
        external_id="789",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )

    class OkUserService:
        async def get_user(
            self, external_id: str, messenger_type: object
        ) -> User | None:
            return ok_user

    messenger_client = FakeMessengerClient()
    message = IncomingMessage(
        chat_id="789",
        user=IncomingUser(
            external_id="789",
            messenger_type=MessengerType.TELEGRAM,
        ),
        text="hi",
    )
    result = await get_user_and_ensure_allowed(
        message,
        messenger_client,
        OkUserService(),
        user_not_found_msg="Not found",
        blocked_msg="Blocked",
        pause_msg="Pause",
    )
    assert result is ok_user
    assert result is not None


@pytest.mark.asyncio
async def test_get_user_and_ensure_allowed_callback_ok() -> None:
    """Callback variant returns user when allowed."""

    ok_user = User(
        user_id=uuid4(),
        external_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )

    class OkUserService:
        async def get_user(
            self, external_id: str, messenger_type: object
        ) -> User | None:
            return ok_user

    messenger_client = FakeMessengerClient()
    callback = IncomingCallback(
        callback_id="cb-1",
        chat_id="999",
        user=IncomingUser(
            external_id="999",
            messenger_type=MessengerType.TELEGRAM,
        ),
        data="x",
        message_id="1",
    )
    result = await get_user_and_ensure_allowed_callback(
        callback,
        messenger_client,
        OkUserService(),
        user_not_found_msg="Not found",
        blocked_msg="Blocked",
        pause_msg="Pause",
    )
    assert result is ok_user
    assert messenger_client.answered_callbacks == []


@pytest.mark.asyncio
async def test_send_text_or_answer_handles_type_error() -> None:
    """Fallback to answer(text) when keyboard arg is unsupported."""
    calls: list[str] = []

    async def answer(text: str) -> None:
        calls.append(text)

    await _send_text_or_answer(
        None,
        chat_id="1",
        text="hello",
        answer=answer,
        keyboard=None,
    )
    assert calls == ["hello"]


@pytest.mark.asyncio
async def test_send_with_retry_uses_send_message() -> None:
    """send_with_retry falls back to send_message."""

    class DummyBot:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str, object]] = []

        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.calls.append((chat_id, text, kwargs.get("reply_markup")))

    bot = DummyBot()
    ok = await send_with_retry(
        bot,
        chat_id="1",
        text="hi",
        retries=1,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
        keyboard=None,
    )
    assert ok is True
    assert bot.calls


@pytest.mark.asyncio
async def test_send_with_retry_invalid_client_returns_false() -> None:
    """send_with_retry returns False when no send methods."""
    ok = await send_with_retry(
        object(),
        chat_id="1",
        text="hi",
        retries=1,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
    )
    assert ok is False


@pytest.mark.asyncio
async def test_answer_callback_or_fallback_uses_answer() -> None:
    """Fallback to callback.answer when no messenger client."""
    calls: list[str] = []

    async def answer(text: str) -> None:
        calls.append(text)

    await _answer_callback_or_fallback(
        None, callback_id="", text="ok", answer=answer
    )
    assert calls == ["ok"]


@pytest.mark.asyncio
async def test_legacy_messenger_client_uses_bot_send_message() -> None:
    """LegacyMessengerClient sends via bot when no answer."""

    class DummyBot:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str]] = []

        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.calls.append((chat_id, text))

    class DummyEvent:
        def __init__(self) -> None:
            self.bot = DummyBot()

    event = DummyEvent()
    client = LegacyMessengerClient(event)
    await client.send_text(chat_id="1", text="hello")
    assert event.bot.calls == [(1, "hello")]


@pytest.mark.asyncio
async def test_legacy_messenger_client_send_photo_via_bot() -> None:
    """LegacyMessengerClient sends photo via bot."""

    class DummyBot:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str]] = []

        async def send_photo(self, chat_id: int, photo: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.calls.append((chat_id, photo))

    class DummyEvent:
        def __init__(self) -> None:
            self.bot = DummyBot()

    event = DummyEvent()
    client = LegacyMessengerClient(event)
    await client.send_photo(chat_id="2", file_id="file")
    assert event.bot.calls == [(2, "file")]


@pytest.mark.asyncio
async def test_legacy_messenger_client_edit_text_uses_event() -> None:
    """LegacyMessengerClient edits text via event method."""
    calls: list[str] = []

    class DummyEvent:
        async def edit_text(self, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            calls.append(text)

    client = LegacyMessengerClient(DummyEvent())
    await client.edit_text(chat_id="1", message_id="1", text="edit")
    assert calls == ["edit"]


@pytest.mark.asyncio
async def test_legacy_messenger_client_edit_markup_uses_event() -> None:
    """LegacyMessengerClient edits reply markup via event method."""
    calls: list[object] = []

    class DummyEvent:
        async def edit_reply_markup(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            calls.append(kwargs.get("reply_markup"))

    client = LegacyMessengerClient(DummyEvent())
    await client.edit_reply_markup(chat_id="1", message_id="1", keyboard=None)
    assert calls == [None]


# ---------------------------------------------------------------------------
# resolve_currency_symbol
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_currency_symbol_with_country() -> None:
    """Returns country currency symbol when user has a country code."""
    from datetime import datetime, timezone

    from ugc_bot.bot.handlers.utils import resolve_currency_symbol
    from ugc_bot.domain.entities import Country
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryCountryRepository,
    )

    country_repo = InMemoryCountryRepository(
        countries={
            "kz": Country(
                code="kz",
                name_native="Қазақстан",
                currency_code="KZT",
                currency_symbol="₸",
            )
        }
    )
    user = User(
        user_id=uuid4(),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="u1",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        country="kz",
    )
    symbol = await resolve_currency_symbol(user, country_repo)
    assert symbol == "₸"


@pytest.mark.asyncio
async def test_resolve_currency_symbol_unknown_country_returns_default() -> (
    None
):
    """Returns default when country code not found in repo."""
    from datetime import datetime, timezone

    from ugc_bot.bot.handlers.utils import resolve_currency_symbol
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryCountryRepository,
    )

    country_repo = InMemoryCountryRepository(countries={})
    user = User(
        user_id=uuid4(),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="u2",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        country="xx",
    )
    symbol = await resolve_currency_symbol(user, country_repo, default="€")
    assert symbol == "€"


@pytest.mark.asyncio
async def test_resolve_currency_symbol_no_country_returns_default() -> None:
    """Returns default when user has no country set."""
    from datetime import datetime, timezone

    from ugc_bot.bot.handlers.utils import resolve_currency_symbol
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryCountryRepository,
    )

    country_repo = InMemoryCountryRepository(countries={})
    user = User(
        user_id=uuid4(),
        external_id="3",
        messenger_type=MessengerType.TELEGRAM,
        username="u3",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        country=None,
    )
    symbol = await resolve_currency_symbol(user, country_repo)
    assert symbol == "₽"


def _make_config_with_docs(**docs_kwargs: str):
    """Build minimal AppConfig with custom docs URLs."""
    from ugc_bot.config import AppConfig

    env = {
        "BOT_TOKEN": "t",
        "DATABASE_URL": "sqlite:///",
        "ADMIN_USERNAME": "a",
        "ADMIN_PASSWORD": "p",
        "ADMIN_SECRET": "s",
    }
    env.update(docs_kwargs)
    return AppConfig.model_validate(env)


def test_format_agreements_message_ru_country_uses_ru_urls() -> None:
    """format_agreements_message uses RU URLs for country_code='ru'."""
    config = _make_config_with_docs(
        DOCS_OFFER_URL="https://ru/offer",
        DOCS_PRIVACY_URL="https://ru/privacy",
        DOCS_CONSENT_URL="https://ru/consent",
        DOCS_OFFER_URL_INTL="https://intl/offer",
        DOCS_PRIVACY_URL_INTL="https://intl/privacy",
        DOCS_CONSENT_URL_INTL="https://intl/consent",
    )
    result = format_agreements_message(config, country_code="ru")
    assert "https://ru/offer" in result
    assert "https://intl/offer" not in result


def test_format_agreements_message_intl_country_uses_intl_urls() -> None:
    """format_agreements_message uses INTL URLs for non-RU country."""
    config = _make_config_with_docs(
        DOCS_OFFER_URL="https://ru/offer",
        DOCS_PRIVACY_URL="https://ru/privacy",
        DOCS_CONSENT_URL="https://ru/consent",
        DOCS_OFFER_URL_INTL="https://intl/offer",
        DOCS_PRIVACY_URL_INTL="https://intl/privacy",
        DOCS_CONSENT_URL_INTL="https://intl/consent",
    )
    result = format_agreements_message(config, country_code="kz")
    assert "https://intl/offer" in result
    assert "https://ru/offer" not in result


def test_format_agreements_message_none_country_uses_ru_urls() -> None:
    """format_agreements_message uses RU URLs when country_code is None."""
    config = _make_config_with_docs(
        DOCS_OFFER_URL="https://ru/offer",
        DOCS_OFFER_URL_INTL="https://intl/offer",
    )
    result = format_agreements_message(config, country_code=None)
    assert "https://ru/offer" in result


def test_format_agreements_message_intl_fallback_to_ru() -> None:
    """format_agreements_message falls back to RU when INTL is empty."""
    config = _make_config_with_docs(
        DOCS_OFFER_URL="https://ru/offer",
        DOCS_PRIVACY_URL="https://ru/privacy",
        DOCS_CONSENT_URL="https://ru/consent",
    )
    result = format_agreements_message(config, country_code="kz")
    assert "https://ru/offer" in result
