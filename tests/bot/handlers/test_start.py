"""Tests for start and role handlers."""

import pytest

from tests.helpers.fakes import (
    FakeCallback,
    FakeFSMContext,
    FakeMessage,
    FakeMessengerClient,
    FakeReferralService,
    FakeUser,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.advertiser_registration import (
    choose_advertiser_role,
)
from ugc_bot.bot.telegram.handlers.blogger_registration import (
    choose_creator_role,
)
from ugc_bot.bot.telegram.handlers.keyboards import (
    advertiser_menu_inline_keyboard,
    creator_filled_profile_inline_keyboard,
    creator_start_keyboard,
    main_menu_inline_keyboard,
    role_inline_keyboard,
)
from ugc_bot.bot.telegram.handlers.start import (
    change_role_button,
    change_role_callback,
    country_selected,
    start_command,
    support_button,
    support_callback,
)
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.domain.enums import MessengerType

_TEXTS_RU = DEFAULT_TEXTS["ru"]
_ROLE_KEYS = ["btn_creator", "btn_advertiser", "btn_support"]


@pytest.mark.asyncio
async def test_start_command_sends_role_keyboard(
    user_repo, messenger_client, event_adapter, config, bot_texts_service
) -> None:
    """Ensure /start sends role keyboard and start text."""

    service = UserRoleService(user_repo=user_repo)
    referral_service = FakeReferralService()
    message = FakeMessage(text=None, user=FakeUser(1, "test", "Alice"))
    state = FakeFSMContext(state=None)
    await start_command(
        message,
        state=state,
        user_role_service=service,
        referral_service=referral_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert message.answers
    assert _TEXTS_RU["start_message"] in message.answers[0][0]
    keyboard = message.answers[0][1]
    assert keyboard is not None
    role_texts = {k: _TEXTS_RU[k] for k in _ROLE_KEYS}
    assert keyboard.rows == role_inline_keyboard(role_texts).rows


@pytest.mark.asyncio
async def test_start_command_with_referral_code_saves_pending(
    user_repo, messenger_client, event_adapter, config, bot_texts_service
) -> None:
    """Start with referral code in text calls save_pending_referral."""

    class RecordingReferralService(FakeReferralService):
        def parse_referral_code(self, text: str | None) -> str | None:
            return "ref_123" if text and "ref" in text else None

        def __init__(self) -> None:
            self.save_calls: list[tuple[object, str]] = []

        async def save_pending_referral(
            self, user_id: object, code: str
        ) -> bool:
            self.save_calls.append((user_id, code))
            return True

    service = UserRoleService(user_repo=user_repo)
    referral_service = RecordingReferralService()
    message = FakeMessage(
        text="/start ref_123", user=FakeUser(1, "test", "Alice")
    )
    state = FakeFSMContext(state=None)
    await start_command(
        message,
        state=state,
        user_role_service=service,
        referral_service=referral_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert len(referral_service.save_calls) == 1
    assert referral_service.save_calls[0][1] == "ref_123"


@pytest.mark.asyncio
async def test_start_command_without_from_user_returns_early(
    user_repo, messenger_client, event_adapter, config, bot_texts_service
) -> None:
    """Start with no from_user does not send message."""

    service = UserRoleService(user_repo=user_repo)
    referral_service = FakeReferralService()
    message = FakeMessage(text=None, user=None)
    state = FakeFSMContext(state=None)
    await start_command(
        message,
        state=state,
        user_role_service=service,
        referral_service=referral_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert not message.answers


@pytest.mark.asyncio
async def test_start_command_clears_fsm_state(
    user_repo, messenger_client, event_adapter, config, bot_texts_service
) -> None:
    """Start command clears FSM so user always sees role selection."""
    service = UserRoleService(user_repo=user_repo)
    referral_service = FakeReferralService()
    message = FakeMessage(text="/start", user=FakeUser(1, "test", "Alice"))
    state = FakeFSMContext(state="BloggerRegistrationStates:instagram")
    await start_command(
        message,
        state=state,
        user_role_service=service,
        referral_service=referral_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert state.cleared is True
    assert message.answers
    assert "UMC — сервис для UGC" in message.answers[0][0]


@pytest.mark.asyncio
async def test_change_role_button_shows_start_screen(
    messenger_client, event_adapter, config, bot_texts_service
) -> None:
    """Change role button shows start text and role keyboard."""

    message = FakeMessage(
        text=_TEXTS_RU["btn_change_role"], user=FakeUser(1, "u", "User")
    )
    state = FakeFSMContext(state=None)
    await change_role_button(
        message,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert message.answers
    assert _TEXTS_RU["start_message"] in message.answers[0][0]
    assert message.answers[0][1] is not None
    role_texts = {k: _TEXTS_RU[k] for k in _ROLE_KEYS}
    assert message.answers[0][1].rows == role_inline_keyboard(role_texts).rows


@pytest.mark.asyncio
async def test_choose_role_creator_persists(
    user_repo,
    blogger_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Creator role persisted; no profile shows create profile."""

    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(
        text=_TEXTS_RU["btn_creator"], user=FakeUser(42, "bob", "Bob")
    )
    state = FakeFSMContext(state=None)
    await choose_creator_role(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    user = await service.get_user("42", MessengerType.TELEGRAM)
    assert user is not None
    assert user.username == ""
    assert message.answers
    assert _TEXTS_RU["msg_creator_intro"] in message.answers[-1][0]
    assert message.answers[-1][1].rows == creator_start_keyboard(_TEXTS_RU).rows


@pytest.mark.asyncio
async def test_choose_role_creator_with_filled_profile_shows_menu(
    user_repo,
    blogger_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Creator with filled blogger profile: show Edit/My profile/My orders."""

    from tests.helpers.factories import create_test_blogger_profile
    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(
        text=_TEXTS_RU["btn_creator"], user=FakeUser(42, "bob", "Bob")
    )
    state = FakeFSMContext(state=None)

    await service.set_user(
        external_id="42",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
        role_chosen=False,
    )
    user = await service.get_user("42", MessengerType.TELEGRAM)
    assert user is not None
    await create_test_blogger_profile(blogger_repo, user.user_id)

    await choose_creator_role(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert message.answers
    assert message.answers[-1][0] == _TEXTS_RU["msg_choose_action"]
    assert (
        message.answers[-1][1].rows
        == creator_filled_profile_inline_keyboard(_TEXTS_RU).rows
    )


@pytest.mark.asyncio
async def test_choose_role_advertiser_with_filled_profile_shows_menu(
    user_repo,
    blogger_repo,
    advertiser_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Advertiser with filled profile: show 'Выберите действие:' and menu."""

    from tests.helpers.factories import create_test_advertiser_profile
    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    message = FakeMessage(
        text=_TEXTS_RU["btn_advertiser"],
        user=FakeUser(99, "adv", "Advertiser"),
    )
    state = FakeFSMContext(state=None)

    await service.set_user(
        external_id="99",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role_chosen=False,
    )
    user = await service.get_user("99", MessengerType.TELEGRAM)
    assert user is not None
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    await choose_advertiser_role(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert message.answers
    assert message.answers[-1][0] == "Выберите действие:"
    assert (
        message.answers[-1][1].rows
        == advertiser_menu_inline_keyboard(_TEXTS_RU).rows
    )


@pytest.mark.asyncio
async def test_choose_role_without_user(
    user_repo, blogger_repo, config, bot_texts_service
) -> None:
    """Ignore messages without sender."""

    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(text=_TEXTS_RU["btn_advertiser"], user=None)
    state = FakeFSMContext(state=None)
    await choose_advertiser_role(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert await service.get_user("0", MessengerType.TELEGRAM) is None


@pytest.mark.asyncio
async def test_choose_role_advertiser_response(
    user_repo, blogger_repo, config, bot_texts_service
) -> None:
    """Advertiser role should respond accordingly."""

    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(
        text=_TEXTS_RU["btn_advertiser"], user=FakeUser(99, None, "Ann")
    )
    state = FakeFSMContext(state=None)
    await choose_advertiser_role(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert message.answers
    assert "Вы выбрали роль" in message.answers[-1][0]
    assert "Давайте создадим профиль" in message.answers[-1][0]


@pytest.mark.asyncio
async def test_support_button_sends_support_text(
    user_repo, blogger_repo, config, bot_texts_service
) -> None:
    """Support button sends support text and main menu."""

    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(text="Поддержка", user=FakeUser(1, "u", "User"))
    state = FakeFSMContext(state=None)

    await support_button(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    assert "Служба поддержки" in message.answers[0][0]
    assert "@usemycontent" in message.answers[0][0]
    assert message.answers[0][1] is not None


@pytest.mark.asyncio
async def test_support_button_without_from_user_returns_early(
    user_repo, blogger_repo, config, bot_texts_service
) -> None:
    """Support button with no from_user does not send message."""

    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(text="Поддержка", user=None)
    state = FakeFSMContext(state=None)

    await support_button(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert not message.answers


@pytest.mark.asyncio
async def test_support_button_clears_fsm_state(
    user_repo, blogger_repo, config, bot_texts_service
) -> None:
    """Support button clears FSM state when in a flow."""

    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(text="Поддержка", user=FakeUser(2, "u", "User"))
    state = FakeFSMContext(state="BloggerRegistrationStates:instagram")

    await support_button(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert state.cleared is True
    assert "Служба поддержки" in message.answers[0][0]


@pytest.mark.asyncio
async def test_support_button_shows_advertiser_menu_when_has_profile(
    user_repo,
    blogger_repo,
    advertiser_repo,
    messenger_client,
    event_adapter,
    config,
    bot_texts_service,
) -> None:
    """Support button shows advertiser menu when user has advertiser profile."""

    from tests.helpers.factories import create_test_advertiser_profile
    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    user = await service.set_user(
        external_id="5",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    message = FakeMessage(
        text="Поддержка", user=FakeUser(5, "adv", "Advertiser")
    )
    state = FakeFSMContext(state=None)

    await support_button(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert message.answers
    assert "Служба поддержки" in message.answers[0][0]
    assert (
        message.answers[0][1].rows
        == advertiser_menu_inline_keyboard(_TEXTS_RU).rows
    )


@pytest.mark.asyncio
async def test_support_callback_sends_support_text_and_inline_menu(
    user_repo, blogger_repo, config, bot_texts_service
) -> None:
    """Support inline button sends support text and inline menu."""

    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(user=FakeUser(1, "u", "User"))
    callback = FakeCallback(
        data="support", user=FakeUser(1, "u", "User"), message=message
    )
    client = FakeMessengerClient()
    state = FakeFSMContext(state=None)

    await support_callback(
        callback,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
    )

    assert len(client.sent_text) == 1
    assert "Служба поддержки" in client.sent_text[0]["text"]
    assert client.sent_text[0]["keyboard"] is not None
    assert (
        client.sent_text[0]["keyboard"].rows
        == main_menu_inline_keyboard(_TEXTS_RU).rows
    )


@pytest.mark.asyncio
async def test_support_callback_with_advertiser_shows_advertiser_menu(
    user_repo,
    blogger_repo,
    advertiser_repo,
    config,
    bot_texts_service,
) -> None:
    """Support inline with advertiser profile shows advertiser menu."""

    from tests.helpers.factories import create_test_advertiser_profile
    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    user = await service.set_user(
        external_id="5",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    message = FakeMessage(user=FakeUser(5, "adv", "Adv"))
    callback = FakeCallback(
        data="support", user=FakeUser(5, "adv", "Adv"), message=message
    )
    client = FakeMessengerClient()
    state = FakeFSMContext(state=None)

    await support_callback(
        callback,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
    )

    assert len(client.sent_text) == 1
    assert (
        client.sent_text[0]["keyboard"].rows
        == advertiser_menu_inline_keyboard(_TEXTS_RU).rows
    )


@pytest.mark.asyncio
async def test_change_role_callback_sends_start_screen(
    config, bot_texts_service
) -> None:
    """Change role inline button sends start text and role keyboard."""

    message = FakeMessage(user=FakeUser(2, "u", "User"))
    callback = FakeCallback(
        data="change_role", user=FakeUser(2, "u", "User"), message=message
    )
    client = FakeMessengerClient()
    state = FakeFSMContext(state=None)

    await change_role_callback(
        callback,
        state=state,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
    )

    assert len(client.sent_text) == 1
    assert (
        "UMC" in client.sent_text[0]["text"]
        or "роль" in client.sent_text[0]["text"]
    )
    role_texts = {k: _TEXTS_RU[k] for k in _ROLE_KEYS}
    assert (
        client.sent_text[0]["keyboard"].rows
        == role_inline_keyboard(role_texts).rows
    )


@pytest.mark.asyncio
async def test_country_selected_saves_country_and_shows_role_keyboard(
    user_repo, config, bot_texts_service
) -> None:
    """country_selected saves country and shows role selection screen."""
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryUserRepository,
    )

    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="99", messenger_type=MessengerType.TELEGRAM, username="u99"
    )
    message = FakeMessage(user=FakeUser(99, "u99", "User"))
    callback = FakeCallback(
        data="country:kz", user=FakeUser(99, "u99", "User"), message=message
    )
    client = FakeMessengerClient()
    state = FakeFSMContext(state=None)

    await country_selected(
        callback,
        state=state,
        user_role_service=service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
    )

    saved = await user_repo.get_by_external("99", MessengerType.TELEGRAM)
    assert saved is not None
    assert saved.country == "kz"
    assert len(client.sent_text) == 1
    # keyboard must be removed from the country selection message
    assert len(client.edited_reply_markups) == 1
    assert client.edited_reply_markups[0]["keyboard"] is None


@pytest.mark.asyncio
async def test_country_selected_ignores_if_country_already_set(
    user_repo, config, bot_texts_service
) -> None:
    """country_selected is a no-op when user already has a country."""
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryUserRepository,
    )

    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="99", messenger_type=MessengerType.TELEGRAM, username="u99"
    )
    await service.set_country(
        external_id="99",
        messenger_type=MessengerType.TELEGRAM,
        country_code="ru",
    )
    message = FakeMessage(user=FakeUser(99, "u99", "User"))
    callback = FakeCallback(
        data="country:kz", user=FakeUser(99, "u99", "User"), message=message
    )
    client = FakeMessengerClient()
    state = FakeFSMContext(state=None)

    await country_selected(
        callback,
        state=state,
        user_role_service=service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
    )

    saved = await user_repo.get_by_external("99", MessengerType.TELEGRAM)
    assert saved is not None
    assert saved.country == "ru"  # country unchanged
    assert len(client.sent_text) == 0
    assert len(client.edited_reply_markups) == 0
