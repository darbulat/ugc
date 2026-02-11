"""Order creation flow: states, constants, and keyboards."""

from aiogram.fsm.state import State, StatesGroup

from ugc_bot.application.messenger.dto import Button

ORDER_FLOW_TYPE = "order_creation"

# Cooperation format: barter only, payment only, or both
COOP_BARTER = "🎁 Бартер"
COOP_PAYMENT = "💰 Оплата"
COOP_BOTH = "🔄 Бартер + оплата"

# Order type button texts (for display and matching)
ORDER_TYPE_UGC_ONLY = "🎥 UGC-видео для бренда"
ORDER_TYPE_UGC_PLUS_PLACEMENT = "📢 UGC + размещение у креатора"

ORDER_PHOTO_ADD = "📷 Добавить фото"
ORDER_PHOTO_SKIP = "⏭ Пропустить"

# Content usage: where UGC video will be used (for offer display)
CONTENT_USAGE_SOCIAL = "📱 В соцсетях бренда"
CONTENT_USAGE_ADS = "📢 В рекламе (таргет, объявления)"
CONTENT_USAGE_BOTH = "🔄 В соцсетях и рекламе"

CONTENT_USAGE_TO_OFFER = {
    CONTENT_USAGE_SOCIAL: "соцсети бренда",
    CONTENT_USAGE_ADS: "реклама (таргет, объявления)",
    CONTENT_USAGE_BOTH: "соцсети и реклама бренда",
}

# Deadlines: preview expected within N days
DEADLINES_3 = "⏱ До 3 дней"
DEADLINES_7 = "⏱ До 7 дней"
DEADLINES_14 = "⏱ До 14 дней"

DEADLINES_TO_OFFER = {
    DEADLINES_3: "превью в течение 3 дней после согласования",
    DEADLINES_7: "превью в течение 7 дней после согласования",
    DEADLINES_14: "превью в течение 14 дней после согласования",
}


class OrderCreationStates(StatesGroup):
    """States for order creation."""

    order_type = State()
    offer_text = State()
    cooperation_format = State()
    price = State()
    barter_description = State()
    bloggers_needed = State()
    product_link = State()
    order_photo = State()
    content_usage = State()
    deadlines = State()
    geography = State()


def order_type_keyboard() -> list[list[Button]]:
    """Keyboard for order type: UGC only or UGC + placement."""
    return [
        [Button(text=ORDER_TYPE_UGC_ONLY)],
        [Button(text=ORDER_TYPE_UGC_PLUS_PLACEMENT)],
    ]


def cooperation_format_keyboard() -> list[list[Button]]:
    """Keyboard for cooperation format."""
    return [
        [Button(text=COOP_BARTER)],
        [Button(text=COOP_PAYMENT)],
        [Button(text=COOP_BOTH)],
    ]


def order_photo_keyboard() -> list[list[Button]]:
    """Keyboard for optional order photo: add or skip."""
    return [
        [Button(text=ORDER_PHOTO_ADD)],
        [Button(text=ORDER_PHOTO_SKIP)],
    ]


def bloggers_needed_keyboard(
    allowed_blogger_counts: frozenset[int],
) -> list[list[Button]]:
    """Keyboard for bloggers needed from allowed config."""
    return [[Button(text=str(c))] for c in sorted(allowed_blogger_counts)]


def content_usage_keyboard() -> list[list[Button]]:
    """Keyboard for content usage."""
    return [
        [Button(text=CONTENT_USAGE_SOCIAL)],
        [Button(text=CONTENT_USAGE_ADS)],
        [Button(text=CONTENT_USAGE_BOTH)],
    ]


def deadlines_keyboard() -> list[list[Button]]:
    """Keyboard for deadlines."""
    return [
        [Button(text=DEADLINES_3)],
        [Button(text=DEADLINES_7)],
        [Button(text=DEADLINES_14)],
    ]
