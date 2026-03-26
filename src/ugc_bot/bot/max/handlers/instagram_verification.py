"""Max handlers for Instagram verification flow."""

import logging
import re

from ugc_bot.application.messenger.dto import IncomingCallback, IncomingMessage
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.telegram.handlers.instagram_verification import (
    _format_verification_instruction,
)
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_PROFILE_CONFIRM_INSTAGRAM,
    blogger_verification_sent_inline_keyboard,
)
from ugc_bot.domain.enums import MessengerType, UserStatus

router = MaxRouter()
logger = logging.getLogger(__name__)


@router.message(
    lambda m: bool(
        m.text and m.text.strip() in ("/verify_instagram", "/confirm_instagram")
    )
)
async def start_verification(incoming: IncomingMessage, deps: dict) -> None:
    """Start Instagram verification: send instruction then code."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    profile_service: ProfileService = deps["profile_service"]
    instagram_verification_service: InstagramVerificationService = deps[
        "instagram_verification_service"
    ]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    config = deps["config"]
    locale: str = deps.get("locale", "ru")

    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_user_not_found_start",
            "msg_instagram_blocked",
            "msg_instagram_pause",
        ],
        locale,
    )

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_user_not_found_start", ""),
        )
        return
    if user.status == UserStatus.BLOCKED:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_instagram_blocked", ""),
        )
        return
    if user.status == UserStatus.PAUSE:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_instagram_pause", ""),
        )
        return

    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        msg_empty = await bot_texts_service.get(
            "msg_profile_empty_creator", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_empty,
        )
        return

    if blogger_profile.confirmed:
        msg_confirmed = await bot_texts_service.get(
            "msg_instagram_already_confirmed", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_confirmed,
        )
        return

    verification = await instagram_verification_service.generate_code(
        user.user_id
    )
    await state_store.clear()

    instruction_template = await bot_texts_service.get(
        "msg_instagram_verify_instruction", locale
    )
    # Strip HTML formatting for Max — just format the URL as plain text
    instruction = _format_verification_instruction(
        instruction_template, config.instagram.admin_instagram_username
    )
    # Remove HTML tags for plain-text delivery
    instruction_plain = re.sub(r"<[^>]+>", "", instruction)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=instruction_plain,
    )

    texts = await bot_texts_service.get_many(["btn_my_profile"], locale)
    # Send verification code as plain text (no <code> tags)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=verification.code,
        keyboard=blogger_verification_sent_inline_keyboard(texts),
    )


@router.callback(lambda cb: cb.data == CALLBACK_PROFILE_CONFIRM_INSTAGRAM)
async def start_verification_from_profile_callback(
    incoming: IncomingCallback, deps: dict
) -> None:
    """Start Instagram verification from profile inline menu."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    profile_service: ProfileService = deps["profile_service"]
    instagram_verification_service: InstagramVerificationService = deps[
        "instagram_verification_service"
    ]
    bot_texts_service = deps["bot_texts_service"]
    state_store = deps["state_store"]
    config = deps["config"]
    locale: str = deps.get("locale", "ru")

    await messenger_client.answer_callback(callback_id=incoming.callback_id)

    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_user_not_found_start",
            "msg_instagram_blocked",
            "msg_instagram_pause",
        ],
        locale,
    )

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_user_not_found_start", ""),
        )
        return
    if user.status == UserStatus.BLOCKED:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_instagram_blocked", ""),
        )
        return
    if user.status == UserStatus.PAUSE:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_instagram_pause", ""),
        )
        return

    blogger_profile = await profile_service.get_blogger_profile(user.user_id)
    if blogger_profile is None:
        msg_empty = await bot_texts_service.get(
            "msg_profile_empty_creator", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_empty,
        )
        return
    if blogger_profile.confirmed:
        msg_confirmed = await bot_texts_service.get(
            "msg_instagram_already_confirmed", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_confirmed,
        )
        return

    verification = await instagram_verification_service.generate_code(
        user.user_id
    )
    await state_store.clear()

    instruction_template = await bot_texts_service.get(
        "msg_instagram_verify_instruction", locale
    )
    instruction = _format_verification_instruction(
        instruction_template, config.instagram.admin_instagram_username
    )
    instruction_plain = re.sub(r"<[^>]+>", "", instruction)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=instruction_plain,
    )

    texts = await bot_texts_service.get_many(["btn_my_profile"], locale)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=verification.code,
        keyboard=blogger_verification_sent_inline_keyboard(texts),
    )
