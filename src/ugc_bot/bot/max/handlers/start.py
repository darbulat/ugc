"""Max messenger /start handler."""

from ugc_bot.application.messenger.dto import IncomingMessage
from ugc_bot.bot.max.router import MaxRouter

router = MaxRouter()


@router.message(lambda m: bool(m.text and m.text.startswith("/start")))
async def start_handler(incoming: IncomingMessage, deps: dict) -> None:
    messenger_client = deps["messenger_client"]
    user_role_service = deps["user_role_service"]

    user = await user_role_service.set_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
        username=incoming.user.username or "",
    )

    locale = user.language or "ru"
    bot_texts_service = deps.get("bot_texts_service")
    welcome = "Добро пожаловать!"
    if bot_texts_service:
        welcome = (
            await bot_texts_service.get("start_welcome", locale) or welcome
        )

    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=welcome,
    )
