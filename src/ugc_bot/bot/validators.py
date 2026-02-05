"""Input validators for bot handlers.

All functions return str | None: error message on failure, None on success.
"""

from urllib.parse import urlparse

# Order creation
OFFER_TEXT_MIN = 20
OFFER_TEXT_MAX = 2000
BARTER_DESCRIPTION_MIN = 10
BARTER_DESCRIPTION_MAX = 500
PRODUCT_LINK_MAX = 500
GEOGRAPHY_MAX = 500

# Advertiser registration
NAME_MIN = 2
NAME_MAX = 100
PHONE_DIGITS_MIN = 10
PHONE_DIGITS_MAX = 11
BRAND_MIN = 2
BRAND_MAX = 200
CITY_MAX = 100
COMPANY_ACTIVITY_MAX = 500
SITE_LINK_MAX = 500

# Blogger registration
NICKNAME_MIN = 2
NICKNAME_MAX = 50
TOPICS_MAX = 10
AUDIENCE_GEO_MAX = 200
URL_MAX = 500


def _digits_only(s: str) -> str:
    """Extract digits from string."""
    return "".join(c for c in s if c.isdigit())


def validate_offer_text(value: str) -> str | None:
    """Validate order offer text length."""
    v = (value or "").strip()
    if len(v) < OFFER_TEXT_MIN:
        return f"Опишите задачу подробнее (минимум {OFFER_TEXT_MIN} символов)."
    if len(v) > OFFER_TEXT_MAX:
        return f"Текст слишком длинный (максимум {OFFER_TEXT_MAX} символов)."
    return None


def validate_barter_description(value: str, required: bool) -> str | None:
    """Validate barter description."""
    v = (value or "").strip()
    if required and not v:
        return "Опишите бартерное предложение."
    if v and len(v) < BARTER_DESCRIPTION_MIN:
        return f"Опишите бартер (мин. {BARTER_DESCRIPTION_MIN} символов)."
    if len(v) > BARTER_DESCRIPTION_MAX:
        return f"Текст длинный (макс. {BARTER_DESCRIPTION_MAX} символов)."
    return None


def validate_url(value: str, max_len: int = URL_MAX) -> str | None:
    """Validate URL format (http/https) and length."""
    v = (value or "").strip()
    if not v:
        return None
    if len(v) > max_len:
        return f"Ссылка слишком длинная (максимум {max_len} символов)."
    parsed = urlparse(v)
    if not parsed.scheme or parsed.scheme not in ("http", "https"):
        return "Введите ссылку (http:// или https://)."
    if not parsed.netloc:
        return "Введите корректную ссылку."
    return None


def validate_product_link(value: str) -> str | None:
    """Validate product link (required, URL format)."""
    v = (value or "").strip()
    if not v:
        return "Ссылка не может быть пустой. Введите снова:"
    return validate_url(v, max_len=PRODUCT_LINK_MAX)


def validate_geography(value: str) -> str | None:
    """Validate geography field."""
    v = (value or "").strip()
    if not v:
        return "Укажите географию. Примеры: Казань, Москва / РФ"
    if len(v) > GEOGRAPHY_MAX:
        return f"Текст слишком длинный (максимум {GEOGRAPHY_MAX} символов)."
    return None


def validate_name(
    value: str,
    min_len: int = NAME_MIN,
    max_len: int = NAME_MAX,
) -> str | None:
    """Validate name field."""
    v = (value or "").strip()
    if len(v) < min_len:
        return f"Введите минимум {min_len} символа."
    if len(v) > max_len:
        return f"Максимум {max_len} символов."
    return None


def validate_phone(value: str) -> str | None:
    """Validate Russian phone number (10-11 digits)."""
    v = (value or "").strip()
    if not v:
        return "Номер телефона не может быть пустым. Введите снова:"
    digits = _digits_only(v)
    if len(digits) < PHONE_DIGITS_MIN:
        return "Введите корректный номер (10–11 цифр). Пример: 89001110777"
    if len(digits) > PHONE_DIGITS_MAX:
        return "Слишком много цифр. Пример: 89001110777"
    if (
        digits[0] == "8"
        and len(digits) == 11
        or digits[0] == "7"
        and len(digits) == 11
        or len(digits) == 10
    ):
        pass
    else:
        return "Введите корректный номер. Пример: 89001110777"
    return None


def validate_brand(value: str) -> str | None:
    """Validate brand name."""
    v = (value or "").strip()
    if len(v) < BRAND_MIN:
        return f"Введите минимум {BRAND_MIN} символа."
    if len(v) > BRAND_MAX:
        return f"Максимум {BRAND_MAX} символов."
    return None


def validate_city(value: str | None, required: bool = False) -> str | None:
    """Validate city (optional or required)."""
    v = (value or "").strip() or None
    if required and not v:
        return "Укажите город. Введите снова:"
    if v and len(v) > CITY_MAX:
        return f"Максимум {CITY_MAX} символов."
    return None


def validate_company_activity(value: str | None) -> str | None:
    """Validate company activity (optional)."""
    v = (value or "").strip() or None
    if v and len(v) > COMPANY_ACTIVITY_MAX:
        return f"Максимум {COMPANY_ACTIVITY_MAX} символов."
    return None


def validate_site_link(value: str | None) -> str | None:
    """Validate site link (optional, URL if provided)."""
    v = (value or "").strip() or None
    if not v:
        return None
    return validate_url(v, max_len=SITE_LINK_MAX)


def validate_nickname(value: str) -> str | None:
    """Validate blogger nickname."""
    v = (value or "").strip()
    if len(v) < NICKNAME_MIN:
        return f"Введите минимум {NICKNAME_MIN} символа."
    if len(v) > NICKNAME_MAX:
        return f"Максимум {NICKNAME_MAX} символов."
    return None


def validate_topics(topics: list[str]) -> str | None:
    """Validate topics list (1-10 items)."""
    if not topics:
        return "Введите хотя бы одну тематику:"
    if len(topics) > TOPICS_MAX:
        return f"Укажите не более {TOPICS_MAX} тематик."
    return None


def validate_audience_geo(value: str) -> str | None:
    """Validate audience geography."""
    v = (value or "").strip()
    if not v:
        return "Укажите хотя бы один город. Введите снова:"
    if len(v) > AUDIENCE_GEO_MAX:
        return f"Максимум {AUDIENCE_GEO_MAX} символов."
    return None


def validate_price(value: float, max_price: float) -> str | None:
    """Validate price (positive, not exceeding max)."""
    if value <= 0:
        return "Цена должна быть больше 0."
    if value > max_price:
        return f"Сумма превышает максимально допустимую ({max_price:,.0f} ₽)."
    return None
