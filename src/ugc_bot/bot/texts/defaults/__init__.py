"""Default localized bot texts (key -> value per locale).

Used as fallback when bot_texts table has no row for (key, locale).
All bot messages and button labels must have keys here and in DB.
"""

# ru: Russian (current production)
# en: English (for global market)
# kk: Kazakh (Қазақша)
# be: Belarusian (Беларуская)
# uz: Uzbek (O'zbek)

from ugc_bot.bot.texts.defaults.be import BE
from ugc_bot.bot.texts.defaults.en import EN
from ugc_bot.bot.texts.defaults.kk import KK
from ugc_bot.bot.texts.defaults.ru import RU
from ugc_bot.bot.texts.defaults.uz import UZ

DEFAULT_TEXTS: dict[str, dict[str, str]] = {
    "ru": RU,
    "en": EN,
    "kk": KK,
    "be": BE,
    "uz": UZ,
}

for _k in DEFAULT_TEXTS["ru"]:
    if _k not in DEFAULT_TEXTS["kk"]:
        DEFAULT_TEXTS["kk"][_k] = DEFAULT_TEXTS["ru"][_k]
    if _k not in DEFAULT_TEXTS["be"]:
        DEFAULT_TEXTS["be"][_k] = DEFAULT_TEXTS["ru"][_k]
for _k in DEFAULT_TEXTS["en"]:
    if _k not in DEFAULT_TEXTS["uz"]:
        DEFAULT_TEXTS["uz"][_k] = DEFAULT_TEXTS["en"][_k]
