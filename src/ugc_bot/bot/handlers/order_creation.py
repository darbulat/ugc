"""Order creation flow handlers."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message

# Application errors are handled by ErrorHandlerMiddleware
from ugc_bot.application.services.contact_pricing_service import ContactPricingService
from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import (
    get_user_and_ensure_allowed,
    handle_draft_choice,
    parse_user_id_from_state,
)
from ugc_bot.bot.handlers.keyboards import (
    CREATE_ORDER_BUTTON_TEXT,
    DRAFT_QUESTION_TEXT,
    draft_choice_keyboard,
    support_keyboard,
    with_support_keyboard,
)
from ugc_bot.bot.handlers.payments import send_order_invoice
from ugc_bot.bot.handlers.security_warnings import (
    ORDER_CREATED_IMPORTANT,
    ORDER_CREATED_WHAT_NEXT,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import OrderType


router = Router()
logger = logging.getLogger(__name__)

ORDER_FLOW_TYPE = "order_creation"

# Cooperation format: barter only, payment only, or both
COOP_BARTER = "Бартер"
COOP_PAYMENT = "Оплата"
COOP_BOTH = "Бартер + оплата"


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


def _order_type_keyboard() -> list[list[KeyboardButton]]:
    """Keyboard for order type: UGC only or UGC + placement."""
    return [
        [KeyboardButton(text="UGC-видео для бренда")],
        [KeyboardButton(text="UGC + размещение у креатора")],
    ]


def _cooperation_format_keyboard() -> list[list[KeyboardButton]]:
    """Keyboard for cooperation format."""
    return [
        [KeyboardButton(text=COOP_BARTER)],
        [KeyboardButton(text=COOP_PAYMENT)],
        [KeyboardButton(text=COOP_BOTH)],
    ]


def _bloggers_needed_keyboard() -> list[list[KeyboardButton]]:
    """Keyboard for bloggers needed: only 3, 5, 10."""
    return [
        [KeyboardButton(text="3")],
        [KeyboardButton(text="5")],
        [KeyboardButton(text="10")],
    ]


@router.message(Command("create_order"))
@router.message(lambda msg: (msg.text or "").strip() == CREATE_ORDER_BUTTON_TEXT)
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
        blocked_msg="Заблокированные пользователи не могут создавать заказы.",
        pause_msg="Пользователи на паузе не могут создавать заказы.",
    )
    if user is None:
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is None:
        await message.answer(
            "Профиль рекламодателя не заполнен. Команда: /register_advertiser"
        )
        return

    await state.update_data(user_id=user.user_id)
    draft = await fsm_draft_service.get_draft(user.user_id, ORDER_FLOW_TYPE)
    if draft is not None:
        await message.answer(DRAFT_QUESTION_TEXT, reply_markup=draft_choice_keyboard())
        await state.set_state(OrderCreationStates.choosing_draft_restore)
        return
    await message.answer(
        "Что вам нужно?",
        reply_markup=with_support_keyboard(keyboard=_order_type_keyboard()),
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
        first_keyboard=with_support_keyboard(keyboard=_order_type_keyboard()),
        session_expired_msg="Сессия истекла. Начните снова с «Создать заказ».",
    )


@router.message(OrderCreationStates.order_type)
async def handle_order_type(message: Message, state: FSMContext) -> None:
    """Store order type and ask for offer text."""

    text = (message.text or "").strip()
    if text == "UGC-видео для бренда":
        order_type = OrderType.UGC_ONLY
    elif text == "UGC + размещение у креатора":
        order_type = OrderType.UGC_PLUS_PLACEMENT
    else:
        await message.answer(
            "Выберите один из вариантов на клавиатуре.",
            reply_markup=with_support_keyboard(keyboard=_order_type_keyboard()),
        )
        return

    await state.update_data(order_type=order_type.value)
    await message.answer(
        "Кратко опишите задачу для креаторов.\n"
        "Пример: нужны короткие видео для соцсетей с демонстрацией продукта.",
        reply_markup=support_keyboard(),
    )
    await state.set_state(OrderCreationStates.offer_text)


@router.message(OrderCreationStates.offer_text)
async def handle_offer_text(message: Message, state: FSMContext) -> None:
    """Handle offer text and ask cooperation format."""

    offer_text = (message.text or "").strip()
    if not offer_text:
        await message.answer("Текст не может быть пустым. Введите снова:")
        return

    await state.update_data(offer_text=offer_text)
    await message.answer(
        "Какой формат сотрудничества?",
        reply_markup=with_support_keyboard(
            keyboard=_cooperation_format_keyboard(),
        ),
    )
    await state.set_state(OrderCreationStates.cooperation_format)


@router.message(OrderCreationStates.cooperation_format)
async def handle_cooperation_format(message: Message, state: FSMContext) -> None:
    """Store format and ask price and/or barter description."""

    text = (message.text or "").strip()
    if text not in (COOP_BARTER, COOP_PAYMENT, COOP_BOTH):
        await message.answer(
            "Выберите один из вариантов на клавиатуре.",
            reply_markup=with_support_keyboard(
                keyboard=_cooperation_format_keyboard(),
            ),
        )
        return

    await state.update_data(cooperation_format=text)
    if text == COOP_PAYMENT:
        await message.answer(
            "Бюджет за 1 UGC-видео? Укажите цену в рублях:",
            reply_markup=support_keyboard(),
        )
        await state.set_state(OrderCreationStates.price)
        return
    if text == COOP_BARTER:
        await message.answer(
            "Что вы предлагаете по бартеру?\n" "Пример: продукт + доставка",
            reply_markup=support_keyboard(),
        )
        await state.set_state(OrderCreationStates.barter_description)
        return
    # Бартер + оплата
    await message.answer(
        "Бюджет за 1 UGC-видео? Укажите цену в рублях:",
        reply_markup=support_keyboard(),
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

    if price < 0:
        await message.answer("Цена не может быть отрицательной.")
        return

    await state.update_data(price=price)
    data = await state.get_data()
    if data.get("cooperation_format") == COOP_BOTH:
        await message.answer(
            "Что вы предлагаете по бартеру?\n" "Пример: продукт + доставка",
            reply_markup=support_keyboard(),
        )
        await state.set_state(OrderCreationStates.barter_description)
        return
    await message.answer(
        "Сколько креаторов вам нужно?",
        reply_markup=with_support_keyboard(keyboard=_bloggers_needed_keyboard()),
    )
    await state.set_state(OrderCreationStates.bloggers_needed)


@router.message(OrderCreationStates.barter_description)
async def handle_barter_description(message: Message, state: FSMContext) -> None:
    """Handle barter description and ask bloggers needed."""

    barter_description = (message.text or "").strip()
    coop = (await state.get_data()).get("cooperation_format")
    if coop == COOP_BOTH and not barter_description:
        await message.answer("Опишите бартерное предложение:")
        return
    await state.update_data(barter_description=barter_description or None)
    await message.answer(
        "Сколько креаторов вам нужно?",
        reply_markup=with_support_keyboard(keyboard=_bloggers_needed_keyboard()),
    )
    await state.set_state(OrderCreationStates.bloggers_needed)


@router.message(OrderCreationStates.bloggers_needed)
async def handle_bloggers_needed(message: Message, state: FSMContext) -> None:
    """Store bloggers needed (3, 5 or 10) and ask product link."""

    raw = (message.text or "").strip()
    if raw not in ("3", "5", "10"):
        await message.answer(
            "Выберите одно из значений: 3, 5 или 10.",
            reply_markup=with_support_keyboard(keyboard=_bloggers_needed_keyboard()),
        )
        return

    bloggers_needed = int(raw)
    await state.update_data(bloggers_needed=bloggers_needed)
    await message.answer(
        "Введите ссылку на продукт (для откликнувшихся креаторов):",
        reply_markup=support_keyboard(),
    )
    await state.set_state(OrderCreationStates.product_link)


@router.message(OrderCreationStates.product_link)
async def handle_product_link(
    message: Message,
    state: FSMContext,
    order_service: OrderService,
    config: AppConfig,
    contact_pricing_service: ContactPricingService,
) -> None:
    """Handle product link and create order."""

    product_link = (message.text or "").strip()
    if not product_link:
        await message.answer("Ссылка не может быть пустой. Введите снова:")
        return

    data = await state.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await message.answer("Сессия истекла. Начните заново с «Создать заказ».")
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

    if cooperation_format == COOP_BARTER:
        price = 0.0

    order = await order_service.create_order(
        advertiser_id=user_id,
        order_type=order_type,
        product_link=product_link,
        offer_text=offer_text,
        ugc_requirements=None,
        barter_description=barter_description,
        price=price,
        bloggers_needed=bloggers_needed,
    )

    await state.clear()
    await message.answer(
        "Заказ создан. Мы отправим ваше предложение подходящим UGC-креаторам."
    )
    await message.answer(ORDER_CREATED_WHAT_NEXT, parse_mode="Markdown")
    await message.answer(ORDER_CREATED_IMPORTANT, parse_mode="Markdown")

    contact_price = await contact_pricing_service.get_price(bloggers_needed)
    if contact_price is None or contact_price <= 0:
        await message.answer(
            "Стоимость доступа к контактам не настроена. Свяжитесь с поддержкой."
        )
        return
    await send_order_invoice(
        message=message,
        order_id=order.order_id,
        offer_text=order.offer_text,
        price_value=contact_price,
        config=config,
    )
