"""Order creation flow: states, constants, and keyboards."""

from aiogram.fsm.state import State, StatesGroup

from ugc_bot.application.messenger.dto import Button

ORDER_FLOW_TYPE = "order_creation"

# Inline callback_data for order creation (Telegram limit 64 bytes)
CALLBACK_ORDER_TYPE_UGC = "order:type:ugc"
CALLBACK_ORDER_TYPE_PLACEMENT = "order:type:placement"
CALLBACK_ORDER_COOP_BARTER = "order:coop:barter"
CALLBACK_ORDER_COOP_PAYMENT = "order:coop:payment"
CALLBACK_ORDER_COOP_BOTH = "order:coop:both"
CALLBACK_ORDER_PHOTO_ADD = "order:photo:add"
CALLBACK_ORDER_PHOTO_SKIP = "order:photo:skip"
CALLBACK_ORDER_CONTENT_SOCIAL = "order:content:social"
CALLBACK_ORDER_CONTENT_ADS = "order:content:ads"
CALLBACK_ORDER_CONTENT_BOTH = "order:content:both"
CALLBACK_ORDER_DEADLINES_PREFIX = "order:dl:"
CALLBACK_ORDER_BLOGGERS_PREFIX = "order:bloggers:"

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
    """Keyboard for order type: UGC only or UGC + placement (inline)."""
    return [
        [
            Button(
                text=ORDER_TYPE_UGC_ONLY,
                callback_data=CALLBACK_ORDER_TYPE_UGC,
            )
        ],
        [
            Button(
                text=ORDER_TYPE_UGC_PLUS_PLACEMENT,
                callback_data=CALLBACK_ORDER_TYPE_PLACEMENT,
            )
        ],
    ]


def cooperation_format_keyboard() -> list[list[Button]]:
    """Keyboard for cooperation format (inline)."""
    return [
        [Button(text=COOP_BARTER, callback_data=CALLBACK_ORDER_COOP_BARTER)],
        [Button(text=COOP_PAYMENT, callback_data=CALLBACK_ORDER_COOP_PAYMENT)],
        [Button(text=COOP_BOTH, callback_data=CALLBACK_ORDER_COOP_BOTH)],
    ]


def order_photo_keyboard() -> list[list[Button]]:
    """Keyboard for optional order photo: add or skip (inline)."""
    return [
        [Button(text=ORDER_PHOTO_ADD, callback_data=CALLBACK_ORDER_PHOTO_ADD)],
        [
            Button(
                text=ORDER_PHOTO_SKIP, callback_data=CALLBACK_ORDER_PHOTO_SKIP
            )
        ],
    ]


def bloggers_needed_keyboard(
    allowed_blogger_counts: frozenset[int],
) -> list[list[Button]]:
    """Keyboard for bloggers needed (inline, with callback_data)."""
    return [
        [
            Button(
                text=str(c),
                callback_data=f"{CALLBACK_ORDER_BLOGGERS_PREFIX}{c}",
            )
        ]
        for c in sorted(allowed_blogger_counts)
    ]


def content_usage_keyboard() -> list[list[Button]]:
    """Keyboard for content usage (inline)."""
    return [
        [
            Button(
                text=CONTENT_USAGE_SOCIAL,
                callback_data=CALLBACK_ORDER_CONTENT_SOCIAL,
            )
        ],
        [
            Button(
                text=CONTENT_USAGE_ADS,
                callback_data=CALLBACK_ORDER_CONTENT_ADS,
            )
        ],
        [
            Button(
                text=CONTENT_USAGE_BOTH,
                callback_data=CALLBACK_ORDER_CONTENT_BOTH,
            )
        ],
    ]


def deadlines_keyboard() -> list[list[Button]]:
    """Keyboard for deadlines (inline)."""
    return [
        [
            Button(
                text=DEADLINES_3,
                callback_data=f"{CALLBACK_ORDER_DEADLINES_PREFIX}3",
            )
        ],
        [
            Button(
                text=DEADLINES_7,
                callback_data=f"{CALLBACK_ORDER_DEADLINES_PREFIX}7",
            )
        ],
        [
            Button(
                text=DEADLINES_14,
                callback_data=f"{CALLBACK_ORDER_DEADLINES_PREFIX}14",
            )
        ],
    ]
