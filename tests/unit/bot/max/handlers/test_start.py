from unittest.mock import AsyncMock

import pytest

from ugc_bot.application.messenger.dto import IncomingMessage, IncomingUser
from ugc_bot.bot.max.handlers.start import router
from ugc_bot.domain.enums import MessengerType


@pytest.fixture
def incoming_start():
    return IncomingMessage(
        chat_id="100",
        user=IncomingUser(
            external_id="42", messenger_type=MessengerType.MAX, username="alice"
        ),
        text="/start",
        message_id="msg_1",
    )


@pytest.fixture
def deps():
    return {
        "messenger_client": AsyncMock(),
        "user_role_service": AsyncMock(),
        "bot_texts_service": AsyncMock(),
        "state_store": AsyncMock(),
        "config": AsyncMock(),
    }


@pytest.mark.asyncio
async def test_start_handler_sends_welcome(incoming_start, deps):
    deps["user_role_service"].set_user = AsyncMock(
        return_value=AsyncMock(language="ru")
    )
    deps["bot_texts_service"].get = AsyncMock(return_value="Добро пожаловать!")

    await router.route_message(incoming_start, deps)

    deps["messenger_client"].send_text.assert_called_once()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs["chat_id"] == "100"
