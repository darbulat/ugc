"""Order creation flow handlers."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, Message

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.contact_pricing_service import ContactPricingService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import cancel_keyboard, with_cancel_keyboard
from ugc_bot.bot.handlers.payments import send_order_invoice
from ugc_bot.bot.handlers.security_warnings import ADVERTISER_ORDER_WARNING
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import MessengerType, UserStatus


router = Router()
logger = logging.getLogger(__name__)


class OrderCreationStates(StatesGroup):
    """States for order creation."""

    product_link = State()
    offer_text = State()
    ugc_requirements = State()
    barter_choice = State()
    barter_description = State()
    price = State()
    bloggers_needed = State()


@router.message(Command("create_order"))
async def start_order_creation(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    profile_service: ProfileService,
    order_service: OrderService,
) -> None:
    """Start order creation flow."""

    if message.from_user is None:
        return

    user = user_role_service.get_user(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await message.answer("Пользователь не найден. Выберите роль через /role.")
        return
    if user.status == UserStatus.BLOCKED:
        await message.answer("Заблокированные пользователи не могут создавать заказы.")
        return
    if user.status == UserStatus.PAUSE:
        await message.answer("Пользователи на паузе не могут создавать заказы.")
        return

    advertiser = profile_service.get_advertiser_profile(user.user_id)
    if advertiser is None:
        await message.answer(
            "Профиль рекламодателя не заполнен. Команда: /register_advertiser"
        )
        return

    is_new = order_service.is_new_advertiser(user.user_id)
    await state.update_data(user_id=user.user_id, is_new=is_new)
    await message.answer("Введите ссылку на продукт:", reply_markup=cancel_keyboard())
    await state.set_state(OrderCreationStates.product_link)


@router.message(OrderCreationStates.product_link)
async def handle_product_link(message: Message, state: FSMContext) -> None:
    """Handle product link input."""

    product_link = (message.text or "").strip()
    if not product_link:
        await message.answer("Ссылка не может быть пустой. Введите снова:")
        return

    await state.update_data(product_link=product_link)
    await message.answer(
        "Введите краткий offer для блогеров:",
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(OrderCreationStates.offer_text)


@router.message(OrderCreationStates.offer_text)
async def handle_offer_text(message: Message, state: FSMContext) -> None:
    """Handle offer text input."""

    offer_text = (message.text or "").strip()
    if not offer_text:
        await message.answer("Текст не может быть пустым. Введите снова:")
        return

    await state.update_data(offer_text=offer_text)
    await message.answer(
        "Введите требования к UGC или напишите 'пропустить':",
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(OrderCreationStates.ugc_requirements)


@router.message(OrderCreationStates.ugc_requirements)
async def handle_ugc_requirements(message: Message, state: FSMContext) -> None:
    """Handle UGC requirements input."""

    raw = (message.text or "").strip()
    ugc_requirements = None if raw.lower() == "пропустить" else raw
    await state.update_data(ugc_requirements=ugc_requirements)

    data = await state.get_data()
    if data.get("is_new"):
        await state.update_data(barter_description=None)
        await message.answer(
            "Введите цену за 1 UGC-видео:",
            reply_markup=cancel_keyboard(),
        )
        await state.set_state(OrderCreationStates.price)
        return

    await message.answer(
        "Есть бартер? Выберите:",
        reply_markup=with_cancel_keyboard(
            keyboard=[
                [KeyboardButton(text="Да")],
                [KeyboardButton(text="Нет")],
            ],
        ),
    )
    await state.set_state(OrderCreationStates.barter_choice)


@router.message(OrderCreationStates.barter_choice)
async def handle_barter_choice(message: Message, state: FSMContext) -> None:
    """Handle barter choice input."""

    choice = (message.text or "").strip().lower()
    if choice not in {"да", "нет"}:
        await message.answer("Выберите 'Да' или 'Нет'.")
        return

    if choice == "нет":
        await state.update_data(barter_description=None)
        await message.answer("Введите цену за 1 UGC-видео:")
        await state.set_state(OrderCreationStates.price)
        return

    await message.answer(
        "Опишите бартерную продукцию:",
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(OrderCreationStates.barter_description)


@router.message(OrderCreationStates.barter_description)
async def handle_barter_description(message: Message, state: FSMContext) -> None:
    """Handle barter description input."""

    barter_description = (message.text or "").strip()
    if not barter_description:
        await message.answer("Описание не может быть пустым. Введите снова:")
        return

    await state.update_data(barter_description=barter_description)
    await message.answer(
        "Введите цену за 1 UGC-видео:",
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(OrderCreationStates.price)


@router.message(OrderCreationStates.price)
async def handle_price(message: Message, state: FSMContext) -> None:
    """Handle price input."""

    raw = (message.text or "").replace(",", ".").strip()
    try:
        price = float(raw)
    except ValueError:
        await message.answer("Введите число, например 1500.")
        return

    if price <= 0:
        await message.answer("Цена должна быть больше 0.")
        return

    await state.update_data(price=price)
    data = await state.get_data()
    if data.get("is_new"):
        bloggers_keyboard = [[KeyboardButton(text="3")], [KeyboardButton(text="10")]]
    else:
        bloggers_keyboard = [
            [KeyboardButton(text="3")],
            [KeyboardButton(text="10")],
            [KeyboardButton(text="20")],
            [KeyboardButton(text="30")],
            [KeyboardButton(text="50")],
        ]
    await message.answer(
        "Выберите количество блогеров:",
        reply_markup=with_cancel_keyboard(
            keyboard=bloggers_keyboard,
        ),
    )
    await state.set_state(OrderCreationStates.bloggers_needed)


@router.message(OrderCreationStates.bloggers_needed)
async def handle_bloggers_needed(
    message: Message,
    state: FSMContext,
    order_service: OrderService,
    config: AppConfig,
    contact_pricing_service: ContactPricingService,
) -> None:
    """Finalize order creation."""

    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Выберите одно из значений: 3/10/20/30/50.")
        return

    bloggers_needed = int(raw)
    data = await state.get_data()
    if bloggers_needed not in {3, 10, 20, 30, 50}:
        await message.answer("Выберите одно из значений: 3/10/20/30/50.")
        return
    if data.get("is_new") and bloggers_needed > 10:
        await message.answer("NEW рекламодатели могут выбрать только 3 или 10.")
        return

    try:
        order = order_service.create_order(
            advertiser_id=data["user_id"],
            product_link=data["product_link"],
            offer_text=data["offer_text"],
            ugc_requirements=data.get("ugc_requirements"),
            barter_description=data.get("barter_description"),
            price=data["price"],
            bloggers_needed=bloggers_needed,
        )
    except (OrderCreationError, UserNotFoundError) as exc:
        logger.warning(
            "Order creation failed",
            extra={"user_id": data.get("user_id"), "reason": str(exc)},
        )
        await message.answer(f"Ошибка создания заказа: {exc}")
        return
    except Exception:
        logger.exception(
            "Unexpected error during order creation",
            extra={"user_id": data.get("user_id")},
        )
        await message.answer("Произошла неожиданная ошибка. Попробуйте позже.")
        return

    await state.clear()
    await message.answer(f"Заказ создан со статусом NEW. Номер: {order.order_id}")
    # Send security warning
    await message.answer(ADVERTISER_ORDER_WARNING)
    contact_price = contact_pricing_service.get_price(bloggers_needed)
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
