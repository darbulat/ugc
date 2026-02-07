"""Order creation flow handlers."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.services.contact_pricing_service import (
    ContactPricingService,
)
from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.application.services.order_service import (
    MAX_ORDER_PRICE,
    OrderService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    CREATE_ORDER_BUTTON_TEXT,
    DRAFT_QUESTION_TEXT,
    draft_choice_keyboard,
    flow_keyboard,
    flow_keyboard_remove,
)
from ugc_bot.bot.handlers.payments import send_order_invoice
from ugc_bot.bot.handlers.security_warnings import ORDER_CREATED_MESSAGE
from ugc_bot.bot.handlers.utils import (
    get_user_and_ensure_allowed,
    handle_draft_choice,
    parse_user_id_from_state,
)
from ugc_bot.bot.validators import (
    normalize_url,
    validate_barter_description,
    validate_geography,
    validate_offer_text,
    validate_price,
    validate_product_link,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import OrderType

router = Router()
logger = logging.getLogger(__name__)

ORDER_FLOW_TYPE = "order_creation"

# Cooperation format: barter only, payment only, or both
COOP_BARTER = "🎁 Бартер"
COOP_PAYMENT = "💰 Оплата"
COOP_BOTH = "🔄 Бартер + оплата"

# Order type button texts (for display and matching)
ORDER_TYPE_UGC_ONLY = "🎥 UGC-видео для бренда"
ORDER_TYPE_UGC_PLUS_PLACEMENT = "📢 UGC + размещение у креатора"


class OrderCreationStates(StatesGroup):
    """States for order creation."""

    choosing_draft_restore = State()
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


def _order_type_keyboard() -> list[list[KeyboardButton]]:
    """Keyboard for order type: UGC only or UGC + placement."""
    return [
        [KeyboardButton(text=ORDER_TYPE_UGC_ONLY)],
        [KeyboardButton(text=ORDER_TYPE_UGC_PLUS_PLACEMENT)],
    ]


def _cooperation_format_keyboard() -> list[list[KeyboardButton]]:
    """Keyboard for cooperation format."""
    return [
        [KeyboardButton(text=COOP_BARTER)],
        [KeyboardButton(text=COOP_PAYMENT)],
        [KeyboardButton(text=COOP_BOTH)],
    ]


ORDER_PHOTO_ADD = "📷 Добавить фото"
ORDER_PHOTO_SKIP = "⏭ Пропустить"


def _order_photo_keyboard() -> list[list[KeyboardButton]]:
    """Keyboard for optional order photo: add or skip."""
    return [
        [KeyboardButton(text=ORDER_PHOTO_ADD)],
        [KeyboardButton(text=ORDER_PHOTO_SKIP)],
    ]


def _bloggers_needed_keyboard() -> list[list[KeyboardButton]]:
    """Keyboard for bloggers needed: only 3, 5, 10."""
    return [
        [KeyboardButton(text="3")],
        [KeyboardButton(text="5")],
        [KeyboardButton(text="10")],
    ]


# Content usage: where UGC video will be used (for offer display)
CONTENT_USAGE_SOCIAL = "📱 В соцсетях бренда"
CONTENT_USAGE_ADS = "📢 В рекламе (таргет, объявления)"
CONTENT_USAGE_BOTH = "🔄 В соцсетях и рекламе"

CONTENT_USAGE_TO_OFFER = {
    CONTENT_USAGE_SOCIAL: "соцсети бренда",
    CONTENT_USAGE_ADS: "реклама (таргет, объявления)",
    CONTENT_USAGE_BOTH: "соцсети и реклама бренда",
}


def _content_usage_keyboard() -> list[list[KeyboardButton]]:
    """Keyboard for content usage."""
    return [
        [KeyboardButton(text=CONTENT_USAGE_SOCIAL)],
        [KeyboardButton(text=CONTENT_USAGE_ADS)],
        [KeyboardButton(text=CONTENT_USAGE_BOTH)],
    ]


# Deadlines: preview expected within N days
DEADLINES_3 = "⏱ До 3 дней"
DEADLINES_7 = "⏱ До 7 дней"
DEADLINES_14 = "⏱ До 14 дней"

DEADLINES_TO_OFFER = {
    DEADLINES_3: "превью в течение 3 дней после согласования",
    DEADLINES_7: "превью в течение 7 дней после согласования",
    DEADLINES_14: "превью в течение 14 дней после согласования",
}


def _deadlines_keyboard() -> list[list[KeyboardButton]]:
    """Keyboard for deadlines."""
    return [
        [KeyboardButton(text=DEADLINES_3)],
        [KeyboardButton(text=DEADLINES_7)],
        [KeyboardButton(text=DEADLINES_14)],
    ]


def _keyboard_for_order_state(
    state_key: str, data: dict
) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    """Return reply keyboard for order creation state (draft restore)."""
    keyboards: dict[str, ReplyKeyboardMarkup | ReplyKeyboardRemove] = {
        "OrderCreationStates:order_type": flow_keyboard(
            keyboard=_order_type_keyboard()
        ),
        "OrderCreationStates:offer_text": flow_keyboard_remove(),
        "OrderCreationStates:cooperation_format": flow_keyboard(
            keyboard=_cooperation_format_keyboard()
        ),
        "OrderCreationStates:price": flow_keyboard_remove(),
        "OrderCreationStates:barter_description": flow_keyboard_remove(),
        "OrderCreationStates:bloggers_needed": flow_keyboard(
            keyboard=_bloggers_needed_keyboard()
        ),
        "OrderCreationStates:product_link": flow_keyboard_remove(),
        "OrderCreationStates:order_photo": flow_keyboard(
            keyboard=_order_photo_keyboard()
        ),
        "OrderCreationStates:content_usage": flow_keyboard(
            keyboard=_content_usage_keyboard()
        ),
        "OrderCreationStates:deadlines": flow_keyboard(
            keyboard=_deadlines_keyboard()
        ),
        "OrderCreationStates:geography": flow_keyboard_remove(),
    }
    return keyboards.get(
        state_key,
        flow_keyboard(keyboard=_order_type_keyboard()),
    )


@router.message(Command("create_order"))
@router.message(
    lambda msg: (msg.text or "").strip() == CREATE_ORDER_BUTTON_TEXT
)
async def start_order_creation(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    order_service: OrderService,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Start order creation flow."""

    user = await get_user_and_ensure_allowed(
        message,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Выберите роль через /role.",
        blocked_msg="Заблокированные не могут создавать заказы.",
        pause_msg="На паузе не могут создавать заказы.",
    )
    if user is None:
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is None:
        await message.answer(
            "Профиль рекламодателя не заполнен. Команда: /advertiser"
        )
        return

    await state.update_data(user_id=user.user_id)
    draft = await fsm_draft_service.get_draft(user.user_id, ORDER_FLOW_TYPE)
    if draft is not None:
        await message.answer(
            DRAFT_QUESTION_TEXT, reply_markup=draft_choice_keyboard()
        )
        await state.set_state(OrderCreationStates.choosing_draft_restore)
        return
    await message.answer(
        "Что вам нужно?",
        reply_markup=flow_keyboard(keyboard=_order_type_keyboard()),
    )
    await state.set_state(OrderCreationStates.order_type)


@router.message(OrderCreationStates.choosing_draft_restore)
async def order_draft_choice(
    message: Message,
    state: FSMContext,
    fsm_draft_service: FsmDraftService,
) -> None:
    """Handle Continue or Start over when draft exists."""
    await handle_draft_choice(
        message,
        state,
        fsm_draft_service,
        flow_type=ORDER_FLOW_TYPE,
        user_id_key="user_id",
        first_state=OrderCreationStates.order_type,
        first_prompt="Что вам нужно?",
        first_keyboard=flow_keyboard(keyboard=_order_type_keyboard()),
        session_expired_msg="Сессия истекла. Начните с «Создать заказ».",
        keyboard_for_restored_state=_keyboard_for_order_state,
    )


@router.message(OrderCreationStates.order_type)
async def handle_order_type(message: Message, state: FSMContext) -> None:
    """Store order type and ask for offer text."""

    text = (message.text or "").strip()
    if text == ORDER_TYPE_UGC_ONLY:
        order_type = OrderType.UGC_ONLY
    elif text == ORDER_TYPE_UGC_PLUS_PLACEMENT:
        order_type = OrderType.UGC_PLUS_PLACEMENT
    else:
        await message.answer(
            "Выберите один из вариантов на клавиатуре.",
            reply_markup=flow_keyboard(keyboard=_order_type_keyboard()),
        )
        return

    await state.update_data(order_type=order_type.value)
    await message.answer(
        "Кратко опишите задачу для креаторов.\n"
        "Что снять и в каком формате. Пример: Видео с распаковкой.",
        reply_markup=flow_keyboard_remove(),
    )
    await state.set_state(OrderCreationStates.offer_text)


@router.message(OrderCreationStates.offer_text)
async def handle_offer_text(message: Message, state: FSMContext) -> None:
    """Handle offer text and ask cooperation format."""

    offer_text = (message.text or "").strip()
    err = validate_offer_text(offer_text)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return

    await state.update_data(offer_text=offer_text)
    await message.answer(
        "Какой формат сотрудничества вам подходит?",
        reply_markup=flow_keyboard(
            keyboard=_cooperation_format_keyboard(),
        ),
    )
    await state.set_state(OrderCreationStates.cooperation_format)


@router.message(OrderCreationStates.cooperation_format)
async def handle_cooperation_format(
    message: Message, state: FSMContext
) -> None:
    """Store format and ask price and/or barter description."""

    text = (message.text or "").strip()
    if text not in (COOP_BARTER, COOP_PAYMENT, COOP_BOTH):
        await message.answer(
            "Выберите один из вариантов на клавиатуре.",
            reply_markup=flow_keyboard(
                keyboard=_cooperation_format_keyboard(),
            ),
        )
        return

    await state.update_data(cooperation_format=text)
    if text == COOP_PAYMENT:
        await message.answer(
            "Бюджет за 1 UGC-видео? Укажите цену в рублях: 500, 1000, 2000",
            reply_markup=flow_keyboard_remove(),
        )
        await state.set_state(OrderCreationStates.price)
        return
    if text == COOP_BARTER:
        await message.answer(
            "Что вы предлагаете по бартеру?\n"
            "Продукт бренда (опишите коротко) + доставка",
            reply_markup=flow_keyboard_remove(),
        )
        await state.set_state(OrderCreationStates.barter_description)
        return
    # Бартер + оплата
    await message.answer(
        "Бюджет за 1 UGC-видео? Укажите цену в рублях: 500, 1000, 2000",
        reply_markup=flow_keyboard_remove(),
    )
    await state.set_state(OrderCreationStates.price)


@router.message(OrderCreationStates.price)
async def handle_price(message: Message, state: FSMContext) -> None:
    """Handle price and optionally ask barter description."""

    raw = (message.text or "").replace(",", ".").strip()
    try:
        price = float(raw)
    except ValueError:
        await message.answer("Введите число, например 1500.")
        return

    err = validate_price(price, MAX_ORDER_PRICE)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return

    await state.update_data(price=price)
    data = await state.get_data()
    if data.get("cooperation_format") == COOP_BOTH:
        await message.answer(
            "Что вы предлагаете по бартеру?\n"
            "Продукт бренда (опишите коротко) + доставка",
            reply_markup=flow_keyboard_remove(),
        )
        await state.set_state(OrderCreationStates.barter_description)
        return
    await message.answer(
        "Сколько креаторов вам нужно?",
        reply_markup=flow_keyboard(keyboard=_bloggers_needed_keyboard()),
    )
    await state.set_state(OrderCreationStates.bloggers_needed)


@router.message(OrderCreationStates.barter_description)
async def handle_barter_description(
    message: Message, state: FSMContext
) -> None:
    """Handle barter description and ask bloggers needed."""

    barter_description = (message.text or "").strip()
    coop = (await state.get_data()).get("cooperation_format")
    required = coop == COOP_BOTH
    err = validate_barter_description(barter_description, required=required)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return
    await state.update_data(barter_description=barter_description or None)
    await message.answer(
        "Сколько креаторов вам нужно?",
        reply_markup=flow_keyboard(keyboard=_bloggers_needed_keyboard()),
    )
    await state.set_state(OrderCreationStates.bloggers_needed)


@router.message(OrderCreationStates.bloggers_needed)
async def handle_bloggers_needed(message: Message, state: FSMContext) -> None:
    """Store bloggers needed (3, 5 or 10) and ask product link."""

    raw = (message.text or "").strip()
    if raw not in ("3", "5", "10"):
        await message.answer(
            "Выберите одно из значений: 3, 5 или 10.",
            reply_markup=flow_keyboard(keyboard=_bloggers_needed_keyboard()),
        )
        return

    bloggers_needed = int(raw)
    await state.update_data(bloggers_needed=bloggers_needed)
    await message.answer(
        "Введите ссылку на продукт (для откликнувшихся креаторов):",
        reply_markup=flow_keyboard_remove(),
    )
    await state.set_state(OrderCreationStates.product_link)


@router.message(OrderCreationStates.product_link)
async def handle_product_link(message: Message, state: FSMContext) -> None:
    """Store product link and ask content usage."""

    product_link = (message.text or "").strip()
    err = validate_product_link(product_link)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return

    await state.update_data(product_link=normalize_url(product_link))
    await message.answer(
        "Прикрепите фото (по желанию).\n"
        "Фотография поможет креатору быстрее понять заказ и повысит отклик "
        "на ваше предложение",
        reply_markup=flow_keyboard(keyboard=_order_photo_keyboard()),
    )
    await state.set_state(OrderCreationStates.order_photo)


@router.message(OrderCreationStates.order_photo)
async def handle_order_photo(message: Message, state: FSMContext) -> None:
    """Handle optional order photo: skip, add, or receive photo."""

    text = (message.text or "").strip()
    if text == ORDER_PHOTO_SKIP:
        await state.update_data(product_photo_file_id=None)
        await message.answer(
            "Где вы планируете использовать UGC-видео?",
            reply_markup=flow_keyboard(
                keyboard=_content_usage_keyboard(),
            ),
        )
        await state.set_state(OrderCreationStates.content_usage)
        return
    if text == ORDER_PHOTO_ADD:
        await message.answer(
            "Отправьте фото продукта:",
            reply_markup=flow_keyboard(keyboard=_order_photo_keyboard()),
        )
        return

    if message.photo:
        file_id = message.photo[-1].file_id
        await state.update_data(product_photo_file_id=file_id)
        await message.answer(
            "Где вы планируете использовать UGC-видео?",
            reply_markup=flow_keyboard(
                keyboard=_content_usage_keyboard(),
            ),
        )
        await state.set_state(OrderCreationStates.content_usage)
        return

    await message.answer(
        "Выберите «Добавить фото» или «Пропустить» на клавиатуре, "
        "либо отправьте фото продукта.",
        reply_markup=flow_keyboard(keyboard=_order_photo_keyboard()),
    )


@router.message(OrderCreationStates.content_usage)
async def handle_content_usage(message: Message, state: FSMContext) -> None:
    """Store content usage and ask deadlines."""

    text = (message.text or "").strip()
    if text not in (
        CONTENT_USAGE_SOCIAL,
        CONTENT_USAGE_ADS,
        CONTENT_USAGE_BOTH,
    ):
        await message.answer(
            "Выберите один из вариантов на клавиатуре.",
            reply_markup=flow_keyboard(keyboard=_content_usage_keyboard()),
        )
        return

    content_usage_offer = CONTENT_USAGE_TO_OFFER.get(text, text)
    await state.update_data(content_usage=content_usage_offer)
    await message.answer(
        "В какие сроки вам нужен контент? Укажите, через сколько дней после "
        "согласования вы ожидаете превью.",
        reply_markup=flow_keyboard(keyboard=_deadlines_keyboard()),
    )
    await state.set_state(OrderCreationStates.deadlines)


@router.message(OrderCreationStates.deadlines)
async def handle_deadlines(message: Message, state: FSMContext) -> None:
    """Store deadlines and ask geography."""

    text = (message.text or "").strip()
    if text not in (DEADLINES_3, DEADLINES_7, DEADLINES_14):
        await message.answer(
            "Выберите один из вариантов на клавиатуре.",
            reply_markup=flow_keyboard(keyboard=_deadlines_keyboard()),
        )
        return

    deadlines_offer = DEADLINES_TO_OFFER.get(text, text)
    await state.update_data(deadlines=deadlines_offer)
    await message.answer(
        "В каких городах или регионах может находиться креатор? Можно указать "
        "от 1 до 10 городов, регионы или написать «РФ». "
        "(Нужно для бартерных заказов и доставки продукта.)",
        reply_markup=flow_keyboard_remove(),
    )
    await state.set_state(OrderCreationStates.geography)


@router.message(OrderCreationStates.geography)
async def handle_geography(
    message: Message,
    state: FSMContext,
    order_service: OrderService,
    config: AppConfig,
    contact_pricing_service: ContactPricingService,
) -> None:
    """Handle geography and create order."""

    geography = (message.text or "").strip()
    err = validate_geography(geography)
    if err is not None:
        await message.answer(err, reply_markup=flow_keyboard_remove())
        return

    data = await state.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await message.answer(
            "Сессия истекла. Начните заново с «Создать заказ»."
        )
        await state.clear()
        return

    order_type_val = data.get("order_type", OrderType.UGC_ONLY.value)
    try:
        order_type = OrderType(order_type_val)
    except ValueError:
        order_type = OrderType.UGC_ONLY

    offer_text = data["offer_text"]
    cooperation_format = data.get("cooperation_format", COOP_PAYMENT)
    price = data.get("price", 0.0)
    barter_description = data.get("barter_description")
    bloggers_needed = data["bloggers_needed"]
    product_link = data["product_link"]
    product_photo_file_id = data.get("product_photo_file_id")
    content_usage = data.get("content_usage")
    deadlines = data.get("deadlines")

    if cooperation_format == COOP_BARTER:
        price = 0.0

    order = await order_service.create_order(
        advertiser_id=user_id,
        order_type=order_type,
        product_link=product_link,
        offer_text=offer_text,
        barter_description=barter_description,
        price=price,
        bloggers_needed=bloggers_needed,
        content_usage=content_usage,
        deadlines=deadlines,
        geography=geography,
        product_photo_file_id=product_photo_file_id,
    )

    await state.clear()
    await message.answer(ORDER_CREATED_MESSAGE, parse_mode="Markdown")
    contact_price = await contact_pricing_service.get_price(bloggers_needed)
    if contact_price is None or contact_price <= 0:
        await message.answer(
            "Стоимость доступа не настроена. Свяжитесь с поддержкой."
        )
        return
    await send_order_invoice(
        message=message,
        order_id=order.order_id,
        offer_text=order.offer_text,
        price_value=contact_price,
        config=config,
    )
