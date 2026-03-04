"""Input validators for bot handlers.

All functions return str | None: error message on failure, None on success.
validate_birth_date returns (date | None, str | None): (parsed_date, None) on
success, (None, error_message) on failure.

When optional `texts` dict is provided (from BotTextsService), error messages
are taken from it by key (e.g. err_not_bot_command). Otherwise English
fallbacks are used.
"""

from datetime import date
from urllib.parse import urlparse


def _msg(
    texts: dict[str, str] | None,
    key: str,
    fallback: str,
    **kwargs: str | int | float,
) -> str:
    """Get localized message from texts or fallback; format with kwargs."""
    template = (texts or {}).get(key) or fallback
    if kwargs:
        return template.format(**kwargs)
    return template


# Keys for validator error messages (for BotTextsService.get_many).
VALIDATOR_ERR_KEYS = (
    "err_not_bot_command",
    "err_offer_text_min",
    "err_offer_text_max",
    "err_barter_required",
    "err_barter_min",
    "err_barter_max",
    "err_url_max",
    "err_url_scheme",
    "err_url_invalid",
    "err_url_example",
    "err_product_link_empty",
    "err_geo_required",
    "err_geo_max",
    "err_min_chars",
    "err_max_chars",
    "err_phone_empty",
    "err_phone_digits",
    "err_phone_too_many",
    "err_phone_invalid",
    "err_birth_date_empty",
    "err_birth_date_format",
    "err_birth_date_digits",
    "err_birth_date_invalid",
    "err_birth_date_future",
    "err_birth_date_min_age",
    "err_birth_date_max_age",
    "err_city_required",
    "err_company_activity_max",
    "err_nickname_no_url",
    "err_topics_empty",
    "err_topics_max",
    "err_audience_geo_empty",
    "err_audience_geo_max",
    "err_price_positive",
    "err_price_max",
)

# Bot commands that must not be saved as user input (e.g. in profile/order).
# /support is allowed (user may mention support in free text). Stored lowercase.
FORBIDDEN_BOT_COMMANDS = frozenset(
    {
        "/start",
        "/profile",
        "/creator",
        "/advertiser",
        "/create_order",
        "/my_orders",
        "/referral",
        "/referral_list",
        "/verify_instagram",
        "/pay_order",
        "/role",
        "/write",
        "/cancel",
    }
)


def validate_not_bot_command(
    value: str,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Reject if value is exactly a bot command (except /support).

    Prevents saving /profile, /creator, /advertiser etc. in profile/order.
    Returns error message if value is a forbidden command, None otherwise.
    """
    v = (value or "").strip()
    if not v:
        return None
    if v.lower() in FORBIDDEN_BOT_COMMANDS:
        return _msg(
            texts,
            "err_not_bot_command",
            "Do not use bot commands as your answer. Enter text again.",
        )
    return None


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
BIRTH_DATE_MIN_AGE = 10
BIRTH_DATE_MAX_AGE = 100


def _digits_only(s: str) -> str:
    """Extract digits from string."""
    return "".join(c for c in s if c.isdigit())


def validate_offer_text(
    value: str,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate order offer text length."""
    v = (value or "").strip()
    err = validate_not_bot_command(v, texts=texts)
    if err is not None:
        return err
    if len(v) < OFFER_TEXT_MIN:
        return _msg(
            texts,
            "err_offer_text_min",
            "Describe the task in more detail (min {min} characters).",
            min=OFFER_TEXT_MIN,
        )
    if len(v) > OFFER_TEXT_MAX:
        return _msg(
            texts,
            "err_offer_text_max",
            "Text too long (max {max} characters).",
            max=OFFER_TEXT_MAX,
        )
    return None


def validate_barter_description(
    value: str,
    required: bool,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate barter description."""
    v = (value or "").strip()
    if v:
        err = validate_not_bot_command(v, texts=texts)
        if err is not None:
            return err
    if required and not v:
        return _msg(
            texts,
            "err_barter_required",
            "Describe the barter offer.",
        )
    if v and len(v) < BARTER_DESCRIPTION_MIN:
        return _msg(
            texts,
            "err_barter_min",
            "Describe the barter (min {min} characters).",
            min=BARTER_DESCRIPTION_MIN,
        )
    if len(v) > BARTER_DESCRIPTION_MAX:
        return _msg(
            texts,
            "err_barter_max",
            "Text too long (max {max} characters).",
            max=BARTER_DESCRIPTION_MAX,
        )
    return None


def normalize_url(value: str) -> str:
    """Add https:// prefix if URL has no scheme. Returns normalized URL."""
    v = (value or "").strip()
    if not v:
        return v
    parsed = urlparse(v)
    if parsed.scheme and parsed.scheme in ("http", "https"):
        return v
    if not parsed.scheme and v:
        return f"https://{v}"
    return v


def normalize_instagram_url(url: str) -> str:
    """Normalize Instagram URL: strip query/fragment, remove www., add https://."""
    s = (url or "").strip()
    if not s:
        return s
    s = s.lower()
    s = s.split("?")[0].split("#")[0].rstrip("?#")
    s = s.replace("www.instagram.com", "instagram.com")
    if not s.startswith("http://") and not s.startswith("https://"):
        s = f"https://{s}"
    return s


def validate_url(
    value: str,
    max_len: int = URL_MAX,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate URL format (http/https or domain without scheme) and length."""
    v = (value or "").strip()
    if not v:
        return None
    if len(v) > max_len:
        return _msg(
            texts,
            "err_url_max",
            "Link too long (max {max} characters).",
            max=max_len,
        )
    parsed = urlparse(v)
    if parsed.scheme and parsed.scheme not in ("http", "https"):
        return _msg(
            texts,
            "err_url_scheme",
            "Enter a link (http:// or https://).",
        )
    if parsed.scheme and parsed.scheme in ("http", "https"):
        if not parsed.netloc:
            return _msg(
                texts,
                "err_url_invalid",
                "Enter a valid link.",
            )
        return None
    parsed_with_scheme = urlparse(f"https://{v}")
    netloc = parsed_with_scheme.netloc or ""
    if not netloc or " " in v:
        return _msg(
            texts,
            "err_url_invalid",
            "Enter a valid link.",
        )
    if "." not in netloc.split(":")[0]:
        return _msg(
            texts,
            "err_url_example",
            "Enter a valid link (e.g. example.com or site.com).",
        )
    return None


def validate_product_link(
    value: str,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate product link (required, URL format)."""
    v = (value or "").strip()
    if not v:
        return _msg(
            texts,
            "err_product_link_empty",
            "Link cannot be empty. Enter again:",
        )
    return validate_url(v, max_len=PRODUCT_LINK_MAX, texts=texts)


def validate_geography(
    value: str,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate geography field."""
    v = (value or "").strip()
    err = validate_not_bot_command(v, texts=texts)
    if err is not None:
        return err
    if not v:
        return _msg(
            texts,
            "err_geo_required",
            "Specify one option: city, region or country. "
            "Examples: London, UK, Worldwide",
        )
    if len(v) > GEOGRAPHY_MAX:
        return _msg(
            texts,
            "err_geo_max",
            "Text too long (max {max} characters).",
            max=GEOGRAPHY_MAX,
        )
    return None


def validate_name(
    value: str,
    min_len: int = NAME_MIN,
    max_len: int = NAME_MAX,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate name field."""
    v = (value or "").strip()
    err = validate_not_bot_command(v, texts=texts)
    if err is not None:
        return err
    if len(v) < min_len:
        return _msg(
            texts,
            "err_min_chars",
            "Enter at least {min} characters.",
            min=min_len,
        )
    if len(v) > max_len:
        return _msg(
            texts,
            "err_max_chars",
            "Max {max} characters.",
            max=max_len,
        )
    return None


def validate_phone(
    value: str,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate Russian phone number (10-11 digits)."""
    v = (value or "").strip()
    if not v:
        return _msg(
            texts,
            "err_phone_empty",
            "Phone number cannot be empty. Enter again:",
        )
    digits = _digits_only(v)
    if len(digits) < PHONE_DIGITS_MIN:
        return _msg(
            texts,
            "err_phone_digits",
            "Enter a valid number (10–11 digits). Example: 89001110777",
        )
    if len(digits) > PHONE_DIGITS_MAX:
        return _msg(
            texts,
            "err_phone_too_many",
            "Too many digits. Example: 89001110777",
        )
    if (
        digits[0] == "8"
        and len(digits) == 11
        or digits[0] == "7"
        and len(digits) == 11
        or len(digits) == 10
    ):
        pass
    else:
        return _msg(
            texts,
            "err_phone_invalid",
            "Enter a valid number. Example: 89001110777",
        )
    return None


def validate_brand(
    value: str,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate brand name."""
    v = (value or "").strip()
    err = validate_not_bot_command(v, texts=texts)
    if err is not None:
        return err
    if len(v) < BRAND_MIN:
        return _msg(
            texts,
            "err_min_chars",
            "Enter at least {min} characters.",
            min=BRAND_MIN,
        )
    if len(v) > BRAND_MAX:
        return _msg(
            texts,
            "err_max_chars",
            "Max {max} characters.",
            max=BRAND_MAX,
        )
    return None


def validate_birth_date(
    value: str,
    texts: dict[str, str] | None = None,
) -> tuple[date | None, str | None]:
    """Validate birth date in DD.MM.YYYY format. Age must be 10-100 years.

    Returns (parsed_date, None) on success, (None, error_message) on failure.
    """
    v = (value or "").strip()
    if not v:
        return (
            None,
            _msg(
                texts,
                "err_birth_date_empty",
                "Enter date of birth as DD.MM.YYYY (e.g. 15.05.1995).",
            ),
        )
    parts = v.split(".")
    if len(parts) != 3:
        return (
            None,
            _msg(
                texts,
                "err_birth_date_format",
                "Invalid format. Use DD.MM.YYYY (e.g. 15.05.1995).",
            ),
        )
    try:
        day = int(parts[0])
        month = int(parts[1])
        year = int(parts[2])
    except ValueError:
        return (
            None,
            _msg(
                texts,
                "err_birth_date_digits",
                "Enter date in digits as DD.MM.YYYY (e.g. 15.05.1995).",
            ),
        )
    try:
        parsed = date(year, month, day)
    except ValueError:
        return (
            None,
            _msg(
                texts,
                "err_birth_date_invalid",
                "Invalid date. Check day, month and year.",
            ),
        )
    today = date.today()
    if parsed > today:
        return (
            None,
            _msg(
                texts,
                "err_birth_date_future",
                "Date of birth cannot be in the future.",
            ),
        )
    age = today.year - parsed.year
    if (today.month, today.day) < (parsed.month, parsed.day):
        age -= 1
    if age < BIRTH_DATE_MIN_AGE:
        return (
            None,
            _msg(
                texts,
                "err_birth_date_min_age",
                "Age must be at least {age} years.",
                age=BIRTH_DATE_MIN_AGE,
            ),
        )
    if age > BIRTH_DATE_MAX_AGE:
        return (
            None,
            _msg(
                texts,
                "err_birth_date_max_age",
                "Enter a real date of birth (age up to {age} years).",
                age=BIRTH_DATE_MAX_AGE,
            ),
        )
    return parsed, None


def validate_city(
    value: str | None,
    required: bool = False,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate city (optional or required)."""
    v = (value or "").strip() or None
    if v:
        err = validate_not_bot_command(v, texts=texts)
        if err is not None:
            return err
    if required and not v:
        return _msg(
            texts,
            "err_city_required",
            "Specify city. Enter again:",
        )
    if v and len(v) > CITY_MAX:
        return _msg(
            texts,
            "err_max_chars",
            "Max {max} characters.",
            max=CITY_MAX,
        )
    return None


def validate_company_activity(
    value: str | None,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate company activity (optional)."""
    v = (value or "").strip() or None
    if v:
        err = validate_not_bot_command(v, texts=texts)
        if err is not None:
            return err
        if len(v) > COMPANY_ACTIVITY_MAX:
            return _msg(
                texts,
                "err_company_activity_max",
                "Max {max} characters.",
                max=COMPANY_ACTIVITY_MAX,
            )
    return None


def validate_site_link(
    value: str | None,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate site link (optional, URL if provided)."""
    v = (value or "").strip() or None
    if not v:
        return None
    return validate_url(v, max_len=SITE_LINK_MAX, texts=texts)


def validate_nickname(
    value: str,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate blogger nickname. Reject Instagram URLs."""
    v = (value or "").strip()
    err = validate_not_bot_command(v, texts=texts)
    if err is not None:
        return err
    if "instagram.com" in v.lower():
        return _msg(
            texts,
            "err_nickname_no_url",
            "Enter name, not an Instagram link.",
        )
    if len(v) < NICKNAME_MIN:
        return _msg(
            texts,
            "err_min_chars",
            "Enter at least {min} characters.",
            min=NICKNAME_MIN,
        )
    if len(v) > NICKNAME_MAX:
        return _msg(
            texts,
            "err_max_chars",
            "Max {max} characters.",
            max=NICKNAME_MAX,
        )
    return None


def validate_topics(
    topics: list[str],
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate topics list (1-10 items)."""
    if not topics:
        return _msg(
            texts,
            "err_topics_empty",
            "Enter at least one topic:",
        )
    if len(topics) > TOPICS_MAX:
        return _msg(
            texts,
            "err_topics_max",
            "Enter no more than {max} topics.",
            max=TOPICS_MAX,
        )
    return None


def validate_audience_geo(
    value: str,
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate audience geography."""
    v = (value or "").strip()
    err = validate_not_bot_command(v, texts=texts)
    if err is not None:
        return err
    if not v:
        return _msg(
            texts,
            "err_audience_geo_empty",
            "Specify at least one city. Enter again:",
        )
    if len(v) > AUDIENCE_GEO_MAX:
        return _msg(
            texts,
            "err_audience_geo_max",
            "Max {max} characters.",
            max=AUDIENCE_GEO_MAX,
        )
    return None


def validate_price(
    value: float,
    max_price: float,
    currency_symbol: str = "₽",
    texts: dict[str, str] | None = None,
) -> str | None:
    """Validate price (positive, not exceeding max)."""
    if value <= 0:
        return _msg(
            texts,
            "err_price_positive",
            "Price must be greater than 0.",
        )
    if value > max_price:
        formatted_max = f"{max_price:,.0f}".replace(",", " ")
        return _msg(
            texts,
            "err_price_max",
            "Amount exceeds maximum allowed ({max} {currency}).",
            max=formatted_max,
            currency=currency_symbol,
        )
    return None
