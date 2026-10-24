"""Reserved native starts terminate here, before ordinary registration.

The production webhook calls this only after its configured secret validation.
Dispatcher fallback receives actual Bot/Update objects, never body proof.
"""

import logging
import re

from aiogram.utils.token import TokenValidationError, extract_bot_id
from fastapi import HTTPException

from ugc_bot.domain.messenger_linking import NativeLinkProposal

logger = logging.getLogger(__name__)


REPLY_COPY = {
    "ru": "Вернитесь в MAX и обновите экран связи. "
    "Проверьте показанный аккаунт Telegram и подтвердите его там. "
    "Это сообщение не подтверждает связь аккаунтов.",
    "en": "Return to MAX and refresh the linking screen. "
    "Check the displayed Telegram identity and confirm it there. "
    "This message does not confirm account linking.",
    "kk": "MAX қолданбасына оралыңыз және байланыстыру экранын жаңартыңыз. "
    "Көрсетілген Telegram аккаунтын тексеріп, сол жерде растаңыз. "
    "Бұл хабарлама аккаунттар байланысын растамайды.",
    "be": "Вярніцеся ў MAX і абнавіце экран сувязі. "
    "Праверце паказаны акаўнт Telegram і пацвердзіце яго там. "
    "Гэта паведамленне не пацвярджае сувязь акаўнтаў.",
    "uz": "MAX ilovasiga qayting va bog‘lash ekranini yangilang. "
    "Ko‘rsatilgan Telegram hisobini tekshirib, o‘sha yerda tasdiqlang. "
    "Bu xabar hisoblar bog‘langanini tasdiqlamaydi.",
}


def reserved_link_text(text: str | None) -> str | None:
    if not text:
        return None
    match = re.match(r"^/start(?:@[A-Za-z0-9_]+)?\s+([\s\S]*)$", text)
    if match and match[1].lstrip().startswith("lk1_"):
        return match[1].strip()
    return None


async def intercept_reserved_link(update, bot, service) -> bool:
    message = update.message
    payload = reserved_link_text(message.text if message else None)
    if payload is None:
        return False
    sender = message.from_user
    if (
        sender is None
        or sender.is_bot
        or message.chat.type != "private"
        or message.chat.id != sender.id
        or service is None
    ):
        return True
    try:
        bot_id = extract_bot_id(bot.token)
        if bot_id != bot.id:
            return True
    except (ValueError, TypeError, TokenValidationError):
        return True
    scope = getattr(service, "scope", None)
    command = message.text.split()[0]
    if "@" in command and (
        scope is None
        or command.split("@", 1)[1].lower() != scope.bot_username.lower()
    ):
        return True
    native = NativeLinkProposal(
        bot_id,
        str(sender.id),
        str(update.update_id),
        str(message.message_id),
        message.date,
        payload,
        sender.full_name[:256],
        sender.username,
    )
    try:
        await service.propose_native(native)
    except Exception:
        logger.error("Reserved messenger proposal was not durably saved")
        raise HTTPException(
            status_code=503, detail="messenger_proposal_not_saved"
        ) from None
    try:
        await bot.send_message(
            message.chat.id,
            REPLY_COPY.get(
                (sender.language_code or "ru").split("-")[0].lower(),
                REPLY_COPY["ru"],
            ),
        )
    except Exception:
        logger.warning("Reserved messenger proposal reply was not delivered")
    return True
