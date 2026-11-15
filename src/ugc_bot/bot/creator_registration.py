"""Registration steps shared by the Telegram and MAX bots."""

from ugc_bot.application.messenger.dto import IncomingCallback
from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.application.messenger.state import StateStore
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_BLOGGER_AGREE,
    blogger_after_registration_inline_keyboard,
    confirm_agreement_inline_keyboard,
)
from ugc_bot.bot.telegram.handlers.utils import format_agreements_message
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import UserStatus


async def show_creator_agreements(
    *,
    chat_id: str,
    messenger_client: MessengerClient,
    bot_texts_service: BotTextsService,
    config: AppConfig,
    locale: str,
    country_code: str | None,
) -> None:
    texts = await bot_texts_service.get_many(
        [
            "btn_confirm_agreement",
            "msg_agreements_intro_creator",
            "msg_agreements_intro_default",
            "msg_label_offer",
            "msg_label_privacy",
            "msg_label_consent",
            "msg_confirm_docs_fallback",
        ],
        locale,
    )
    await messenger_client.send_text(
        chat_id=chat_id,
        text=format_agreements_message(
            config,
            intro=texts.get("msg_agreements_intro_creator", ""),
            texts=texts,
            country_code=country_code,
        ),
        parse_mode="HTML",
        keyboard=confirm_agreement_inline_keyboard(
            CALLBACK_BLOGGER_AGREE, texts
        ),
    )


async def resume_creator_registration(
    incoming: IncomingCallback,
    state_store: StateStore,
    messenger_client: MessengerClient,
    profile_service: ProfileService,
    user_role_service: UserRoleService,
    bot_texts_service: BotTextsService,
    config: AppConfig,
    locale: str,
    agreement_state: str,
) -> None:
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    if user is None or user.status != UserStatus.ACTIVE:
        return
    profile = await profile_service.get_blogger_profile(user.user_id)
    if profile is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=await bot_texts_service.get(
                "msg_profile_empty_creator", locale
            ),
        )
        return
    if profile.agreement_confirmed_at is not None:
        if profile.confirmed:
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=await bot_texts_service.get(
                    "msg_instagram_already_confirmed", locale
                ),
            )
            return
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=await bot_texts_service.get("msg_profile_created", locale),
            keyboard=blogger_after_registration_inline_keyboard(
                await bot_texts_service.get_many(
                    ["btn_confirm_instagram", "btn_my_profile"], locale
                )
            ),
        )
        return

    await state_store.clear()
    await state_store.update_data(user_id=str(user.user_id))
    await state_store.set_state(agreement_state)
    await show_creator_agreements(
        chat_id=incoming.chat_id,
        messenger_client=messenger_client,
        bot_texts_service=bot_texts_service,
        config=config,
        locale=locale,
        country_code=user.country,
    )
