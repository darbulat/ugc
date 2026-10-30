"""Order creation flow: states, constants, and keyboards."""

from aiogram.fsm.state import State, StatesGroup

from ugc_bot.application.messenger.dto import Button

ORDER_FLOW_TYPE = "order_creation"

# Inline callback_data for order creation (Telegram limit 64 bytes)
CALLBACK_ORDER_TYPE_STORIES = "order:type:stories"
ORDER_TYPE_STORIES = "Сторис"
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
    platforms = State()
    accompaniment = State()


def order_type_keyboard(
    texts: dict[str, str] | None = None,
) -> list[list[Button]]:
    """Keyboard for order type: UGC only or UGC + placement (inline)."""
    t = texts or {}
    return [
        [
            Button(
                text=t.get("order_type_stories", ORDER_TYPE_STORIES),
                callback_data=CALLBACK_ORDER_TYPE_STORIES,
            )
        ],
        [
            Button(
                text=t.get("order_type_ugc_only", ORDER_TYPE_UGC_ONLY),
                callback_data=CALLBACK_ORDER_TYPE_UGC,
            )
        ],
        [
            Button(
                text=t.get(
                    "order_type_ugc_placement", ORDER_TYPE_UGC_PLUS_PLACEMENT
                ),
                callback_data=CALLBACK_ORDER_TYPE_PLACEMENT,
            )
        ],
    ]


def cooperation_format_keyboard(
    texts: dict[str, str] | None = None,
) -> list[list[Button]]:
    """Keyboard for cooperation format (inline)."""
    t = texts or {}
    return [
        [
            Button(
                text=t.get("coop_barter", COOP_BARTER),
                callback_data=CALLBACK_ORDER_COOP_BARTER,
            )
        ],
        [
            Button(
                text=t.get("coop_payment", COOP_PAYMENT),
                callback_data=CALLBACK_ORDER_COOP_PAYMENT,
            )
        ],
        [
            Button(
                text=t.get("coop_both", COOP_BOTH),
                callback_data=CALLBACK_ORDER_COOP_BOTH,
            )
        ],
    ]


def order_photo_keyboard(
    texts: dict[str, str] | None = None,
) -> list[list[Button]]:
    """Keyboard for optional order photo: add or skip (inline)."""
    t = texts or {}
    return [
        [
            Button(
                text=t.get("order_photo_add", ORDER_PHOTO_ADD),
                callback_data=CALLBACK_ORDER_PHOTO_ADD,
            )
        ],
        [
            Button(
                text=t.get("order_photo_skip", ORDER_PHOTO_SKIP),
                callback_data=CALLBACK_ORDER_PHOTO_SKIP,
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
        if len(allowed_blogger_counts) <= 10 or c in (10, 20, 30, 50, 100, 200)
    ]


def content_usage_keyboard(
    texts: dict[str, str] | None = None,
) -> list[list[Button]]:
    """Keyboard for content usage (inline)."""
    t = texts or {}
    return [
        [
            Button(
                text=t.get("content_social", CONTENT_USAGE_SOCIAL),
                callback_data=CALLBACK_ORDER_CONTENT_SOCIAL,
            )
        ],
        [
            Button(
                text=t.get("content_ads", CONTENT_USAGE_ADS),
                callback_data=CALLBACK_ORDER_CONTENT_ADS,
            )
        ],
        [
            Button(
                text=t.get("content_both", CONTENT_USAGE_BOTH),
                callback_data=CALLBACK_ORDER_CONTENT_BOTH,
            )
        ],
    ]


def deadlines_keyboard(
    texts: dict[str, str] | None = None,
) -> list[list[Button]]:
    """Keyboard for deadlines (inline)."""
    t = texts or {}
    return [
        [
            Button(
                text=t.get("deadlines_3", DEADLINES_3),
                callback_data=f"{CALLBACK_ORDER_DEADLINES_PREFIX}3",
            )
        ],
        [
            Button(
                text=t.get("deadlines_7", DEADLINES_7),
                callback_data=f"{CALLBACK_ORDER_DEADLINES_PREFIX}7",
            )
        ],
        [
            Button(
                text=t.get("deadlines_14", DEADLINES_14),
                callback_data=f"{CALLBACK_ORDER_DEADLINES_PREFIX}14",
            )
        ],
    ]
