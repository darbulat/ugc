"""Default localized bot texts (key -> value per locale).

Used as fallback when bot_texts table has no row for (key, locale).
All bot messages and button labels must have keys here and in DB.
"""

# ru: Russian (current production)
# en: English (for global market)
# kk: Kazakh (Қазақша)
# be: Belarusian (Беларуская)
# uz: Uzbek (O'zbek)

from ugc_bot.application.customer_workflow_texts import bot_text_defaults
from ugc_bot.bot.texts.defaults.be import BE
from ugc_bot.bot.texts.defaults.customer import CUSTOMER_TEXTS
from ugc_bot.bot.texts.defaults.en import EN
from ugc_bot.bot.texts.defaults.kk import KK
from ugc_bot.bot.texts.defaults.rating import RATING_TEXTS
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

# Shared customer copy also appears in the editable BotTextsService catalogue.

for _locale, _texts in CUSTOMER_TEXTS.items():
    DEFAULT_TEXTS[_locale].update(_texts)

for _locale, _texts in bot_text_defaults().items():
    DEFAULT_TEXTS[_locale].update(_texts)


_RATING_WORK_REQUIRED = {
    "ru": "Оценка доступна участникам заказа после завершения работы автора. Откройте актуальную карточку заказа.",
    "en": "Order participants can rate a creator after the work is completed. Open the current order.",
    "kk": "Автор жұмысын аяқтаған соң тапсырыс қатысушылары баға бере алады. Ағымдағы тапсырысты ашыңыз.",
    "be": "Удзельнікі замовы могуць ацаніць аўтара пасля завяршэння працы. Адкрыйце актуальную замову.",
    "uz": "Buyurtma ishtirokchilari muallif ish tugagach baho bera oladi. Joriy buyurtmani oching.",
}
for _locale, _message in _RATING_WORK_REQUIRED.items():
    DEFAULT_TEXTS[_locale]["msg_rating_work_required"] = _message

for _locale, _texts in RATING_TEXTS.items():
    DEFAULT_TEXTS[_locale].update(_texts)
