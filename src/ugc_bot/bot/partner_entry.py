"""Native partner cabinet entry; identity is resolved only in the signed app."""

from urllib.parse import urlsplit

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS

CALLBACK_PARTNER_OPEN = "partner:open"
_COPY = {
    "ru": (
        "Откройте собственный партнёрский кабинет.",
        "Партнёрский кабинет временно недоступен.",
    ),
    "en": (
        "Open your own partner cabinet.",
        "The partner cabinet is temporarily unavailable.",
    ),
    "kk": (
        "Жеке серіктес кабинетіңізді ашыңыз.",
        "Серіктес кабинеті уақытша қолжетімсіз.",
    ),
    "be": (
        "Адкрыйце свой партнёрскі кабінет.",
        "Партнёрскі кабінет часова недаступны.",
    ),
    "uz": (
        "Shaxsiy hamkor kabinetingizni oching.",
        "Hamkor kabineti vaqtincha mavjud emas.",
    ),
}


def partner_menu_button(texts):
    return Button(
        text=texts.get("btn_partner_program") or _label("ru"),
        callback_data=CALLBACK_PARTNER_OPEN,
    )


def _label(locale):
    return DEFAULT_TEXTS.get(locale, DEFAULT_TEXTS["ru"])["btn_partner_program"]


def _url(config, platform):
    value = (
        (config.max_bot.webhook_url if config.max_bot else "")
        if platform == "max"
        else config.webhook.webhook_base_url
    )
    try:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return None
        base = (
            f"{parsed.scheme}://{parsed.netloc}"
            if platform == "max"
            else value.strip().rstrip("/")
        )
        path = "max_app.html" if platform == "max" else "app.html"
        return f"{base}/miniapp/{path}?view=partner"
    except ValueError:
        return None


async def send_partner_entry(client, chat_id, config, platform, locale):
    words = _COPY.get(locale, _COPY["ru"])
    url = _url(config, platform)
    keyboard = (
        Keyboard(
            kind=KeyboardKind.INLINE,
            rows=[[Button(text=_label(locale), web_app_url=url)]],
        )
        if url
        else None
    )
    await client.send_text(
        chat_id=chat_id, text=words[0] if url else words[1], keyboard=keyboard
    )
