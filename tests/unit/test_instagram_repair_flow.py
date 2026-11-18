"""A repair reuses the existing owner, code and messenger verification flows."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.application.services.test_instagram_verification_service import (
    _seed_profile,
    _seed_user,
    memory_service,
)
from ugc_bot.application.messenger.dto import IncomingCallback, IncomingUser
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.instagram_verification_service import (
    VerificationSuccess,
)
from ugc_bot.bot.max.handlers import profile as max_profile
from ugc_bot.bot.telegram.handlers import profile as tg_profile
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInstagramGraphApiClient,
    InMemoryInstagramVerificationRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [MessengerType.TELEGRAM, MessengerType.MAX])
@pytest.mark.parametrize("found", [True, False])
async def test_repair_button_discards_stale_fsm_and_uses_authenticated_owner(
    channel, found
):
    state = SimpleNamespace(
        clear=AsyncMock(), update_data=AsyncMock(), set_state=AsyncMock()
    )
    client = SimpleNamespace(answer_callback=AsyncMock(), send_text=AsyncMock())
    user = SimpleNamespace(user_id="owner") if found else None
    profiles = SimpleNamespace(
        get_user_by_external=AsyncMock(return_value=user),
        get_blogger_profile=AsyncMock(return_value=object()),
    )
    texts = SimpleNamespace(get=AsyncMock(return_value="Ссылка Instagram"))
    incoming = IncomingCallback(
        chat_id="123",
        callback_id="callback",
        data="instagram:refresh",
        user=IncomingUser(external_id="123", messenger_type=channel),
    )
    if channel == MessengerType.TELEGRAM:
        adapter = SimpleNamespace(from_callback=lambda _: incoming)
        await tg_profile.handle_instagram_refresh_callback(
            object(),
            state,
            profiles,
            texts,
            messenger_client=client,
            event_adapter=adapter,
        )
    else:
        await max_profile.handle_instagram_refresh_callback(
            incoming,
            {
                "state_store": state,
                "messenger_client": client,
                "profile_service": profiles,
                "bot_texts_service": texts,
            },
        )
    profiles.get_user_by_external.assert_awaited_once_with(
        external_id="123",
        messenger_type=channel,
    )
    if found:
        state.clear.assert_awaited_once()
        assert state.update_data.call_args.kwargs["edit_user_id"] == "owner"
        assert (
            state.update_data.call_args.kwargs["editing_field"]
            == "instagram_url"
        )
    else:
        state.update_data.assert_not_called()


@pytest.mark.asyncio
async def test_same_url_repair_requires_fresh_code_for_existing_owner():
    users, profiles = (
        InMemoryUserRepository(),
        InMemoryBloggerProfileRepository(),
    )
    owner = await _seed_user(users)
    await _seed_profile(profiles, owner)
    initial = replace(
        await profiles.get_by_user_id(owner),
        confirmed=True,
        instagram_user_id="old_scoped_id",
    )
    await profiles.save(initial)
    registration = BloggerRegistrationService(
        user_repo=users, blogger_repo=profiles
    )
    message = SimpleNamespace(answer=AsyncMock())
    pending = await tg_profile._blog_update_instagram(
        initial.instagram_url,
        owner,
        message,
        registration,
    )
    assert not pending.confirmed and pending.user_id == owner
    assert pending.city == initial.city and pending.topics == initial.topics
    verification = memory_service(
        user_repo=users,
        blogger_repo=profiles,
        verification_repo=InMemoryInstagramVerificationRepository(),
        instagram_api_client=InMemoryInstagramGraphApiClient(
            username_map={"fresh_scoped_id": "test_user"}
        ),
        profile_maintenance=SimpleNamespace(verified=AsyncMock()),
    )
    code = await verification.generate_code(
        owner, channel=MessengerType.TELEGRAM
    )
    result = await verification.verify_code_by_instagram_sender(
        instagram_sender_id="fresh_scoped_id",
        code=code.code,
        admin_instagram_username="usemycontent",
    )
    assert isinstance(result, VerificationSuccess)
    confirmed = await profiles.get_by_user_id(owner)
    assert confirmed.confirmed and confirmed.user_id == owner
    assert confirmed.instagram_user_id == "fresh_scoped_id"
    verification.profile_maintenance.verified.assert_awaited_once()
    assert (
        verification.profile_maintenance.verified.call_args.kwargs["session"]
        is not None
    )
