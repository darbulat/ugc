"""Order creation flow handlers."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ugc_bot.application.messenger.dto import Button
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.services.contact_pricing_service import (
    ContactPricingService,
)
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    CONFIRM_AGREEMENT_BUTTON_TEXT,
    CREATE_ORDER_BUTTON_TEXT,
    flow_keyboard,
    flow_keyboard_remove,
)
from ugc_bot.bot.handlers.order_creation_states import (
    CONTENT_USAGE_ADS,
    CONTENT_USAGE_BOTH,
    CONTENT_USAGE_SOCIAL,
    CONTENT_USAGE_TO_OFFER,
    COOP_BARTER,
    COOP_BOTH,
    COOP_PAYMENT,
    DEADLINES_3,
    DEADLINES_7,
    DEADLINES_14,
    DEADLINES_TO_OFFER,
    ORDER_PHOTO_ADD,
    ORDER_PHOTO_SKIP,
    ORDER_TYPE_UGC_ONLY,
    ORDER_TYPE_UGC_PLUS_PLACEMENT,
    OrderCreationStates,
    bloggers_needed_keyboard,
    content_usage_keyboard,
    cooperation_format_keyboard,
    deadlines_keyboard,
    order_photo_keyboard,
    order_type_keyboard,
)
from ugc_bot.bot.handlers.payments import send_order_invoice
from ugc_bot.bot.handlers.profile import _ADVERTISER_AGREEMENTS_STATE
from ugc_bot.bot.handlers.security_warnings import ORDER_CREATED_MESSAGE
from ugc_bot.bot.handlers.utils import (
    format_agreements_message,
    get_user_and_ensure_allowed,
    parse_user_id_from_state,
    resolve_messenger_dependencies,
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
from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore

router = Router()
logger = logging.getLogger(__name__)


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
    config: AppConfig,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Start order creation flow."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg="Пользователь не найден. Выберите роль через /role.",
        blocked_msg="Заблокированные не могут создавать заказы.",
        pause_msg="На паузе не могут создавать заказы.",
    )
    if user is None:
        return

    advertiser = await profile_service.get_advertiser_profile(user.user_id)
    if advertiser is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Профиль рекламодателя не заполнен. Команда: /advertiser",
        )
        return

    agreement_confirmed_at = getattr(user, "agreement_confirmed_at", None)
    if agreement_confirmed_at is None:
        agreements_text = format_agreements_message(
            config,
            intro="Пожалуйста, подтвердите согласие с документами платформы.",
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=agreements_text,
            keyboard=flow_keyboard(
                keyboard=[[Button(text=CONFIRM_AGREEMENT_BUTTON_TEXT)]],
            ),
            parse_mode="HTML",
        )
        await state_store.update_data(user_id=user.user_id)
        await state_store.set_state(_ADVERTISER_AGREEMENTS_STATE)
        return

    await state_store.update_data(user_id=user.user_id)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Что вам нужно?",
        keyboard=flow_keyboard(keyboard=order_type_keyboard()),
    )
    await state_store.set_state(OrderCreationStates.order_type.state)


@router.message(OrderCreationStates.order_type)
async def handle_order_type(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store order type and ask for offer text."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    text = (incoming.text or "").strip()
    if text == ORDER_TYPE_UGC_ONLY:
        order_type = OrderType.UGC_ONLY
    elif text == ORDER_TYPE_UGC_PLUS_PLACEMENT:
        order_type = OrderType.UGC_PLUS_PLACEMENT
    else:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Выберите один из вариантов на клавиатуре.",
            keyboard=flow_keyboard(keyboard=order_type_keyboard()),
        )
        return

    await state_store.update_data(order_type=order_type.value)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "Кратко опишите задачу для креаторов.\n"
            "Что снять и в каком формате. Пример: Видео с распаковкой."
        ),
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(OrderCreationStates.offer_text.state)


@router.message(OrderCreationStates.offer_text)
async def handle_offer_text(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle offer text and ask cooperation format."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    offer_text = (incoming.text or "").strip()
    err = validate_offer_text(offer_text)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(offer_text=offer_text)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Какой формат сотрудничества вам подходит?",
        keyboard=flow_keyboard(keyboard=cooperation_format_keyboard()),
    )
    await state_store.set_state(OrderCreationStates.cooperation_format.state)


@router.message(OrderCreationStates.cooperation_format)
async def handle_cooperation_format(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store format and ask price and/or barter description."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    text = (incoming.text or "").strip()
    if text not in (COOP_BARTER, COOP_PAYMENT, COOP_BOTH):
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Выберите один из вариантов на клавиатуре.",
            keyboard=flow_keyboard(keyboard=cooperation_format_keyboard()),
        )
        return

    await state_store.update_data(cooperation_format=text)
    if text == COOP_PAYMENT:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=(
                "Бюджет за 1 UGC-видео? Укажите цену в рублях: 500, 1000, 2000"
            ),
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(OrderCreationStates.price.state)
        return
    if text == COOP_BARTER:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=(
                "Что вы предлагаете по бартеру?\n"
                "Продукт бренда (опишите коротко) + доставка"
            ),
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(
            OrderCreationStates.barter_description.state
        )
        return
    # Бартер + оплата
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=("Бюджет за 1 UGC-видео? Укажите цену в рублях: 500, 1000, 2000"),
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(OrderCreationStates.price.state)


@router.message(OrderCreationStates.price)
async def handle_price(
    message: Message,
    state: FSMContext,
    max_order_price: float,
    allowed_blogger_counts: frozenset[int],
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle price and optionally ask barter description."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    raw = (incoming.text or "").replace(",", ".").strip()
    try:
        price = float(raw)
    except ValueError:
        await messenger_client.send_text(
            chat_id=incoming.chat_id, text="Введите число, например 1500."
        )
        return

    err = validate_price(price, max_order_price)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(price=price)
    data = await state_store.get_data()
    if data.get("cooperation_format") == COOP_BOTH:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=(
                "Что вы предлагаете по бартеру?\n"
                "Продукт бренда (опишите коротко) + доставка"
            ),
            keyboard=flow_keyboard_remove(),
        )
        await state_store.set_state(
            OrderCreationStates.barter_description.state
        )
        return
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Сколько креаторов вам нужно?",
        keyboard=flow_keyboard(
            keyboard=bloggers_needed_keyboard(allowed_blogger_counts)
        ),
    )
    await state_store.set_state(OrderCreationStates.bloggers_needed.state)


@router.message(OrderCreationStates.barter_description)
async def handle_barter_description(
    message: Message,
    state: FSMContext,
    allowed_blogger_counts: frozenset[int],
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle barter description and ask bloggers needed."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    barter_description = (incoming.text or "").strip()
    coop = (await state_store.get_data()).get("cooperation_format")
    required = coop == COOP_BOTH
    err = validate_barter_description(barter_description, required=required)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return
    await state_store.update_data(barter_description=barter_description or None)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Сколько креаторов вам нужно?",
        keyboard=flow_keyboard(
            keyboard=bloggers_needed_keyboard(allowed_blogger_counts)
        ),
    )
    await state_store.set_state(OrderCreationStates.bloggers_needed.state)


@router.message(OrderCreationStates.bloggers_needed)
async def handle_bloggers_needed(
    message: Message,
    state: FSMContext,
    allowed_blogger_counts: frozenset[int],
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store bloggers needed from allowed counts and ask product link."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    raw = (incoming.text or "").strip()
    valid_strs = {str(c) for c in allowed_blogger_counts}
    if raw not in valid_strs:
        counts_str = ", ".join(str(c) for c in sorted(allowed_blogger_counts))
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=f"Выберите одно из значений: {counts_str}.",
            keyboard=flow_keyboard(
                keyboard=bloggers_needed_keyboard(allowed_blogger_counts)
            ),
        )
        return

    bloggers_needed = int(raw)
    await state_store.update_data(bloggers_needed=bloggers_needed)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Введите ссылку на продукт (для откликнувшихся креаторов):",
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(OrderCreationStates.product_link.state)


@router.message(OrderCreationStates.product_link)
async def handle_product_link(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store product link and ask content usage."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    product_link = (incoming.text or "").strip()
    err = validate_product_link(product_link)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    await state_store.update_data(product_link=normalize_url(product_link))
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "Прикрепите фото (по желанию).\n"
            "Фотография поможет креатору быстрее понять заказ и повысит отклик "
            "на ваше предложение"
        ),
        keyboard=flow_keyboard(keyboard=order_photo_keyboard()),
    )
    await state_store.set_state(OrderCreationStates.order_photo.state)


@router.message(OrderCreationStates.order_photo)
async def handle_order_photo(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle optional order photo: skip, add, or receive photo."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    text = (incoming.text or "").strip()
    if text == ORDER_PHOTO_SKIP:
        await state_store.update_data(product_photo_file_id=None)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Где вы планируете использовать UGC-видео?",
            keyboard=flow_keyboard(keyboard=content_usage_keyboard()),
        )
        await state_store.set_state(OrderCreationStates.content_usage.state)
        return
    if text == ORDER_PHOTO_ADD:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Отправьте фото продукта:",
            keyboard=flow_keyboard(keyboard=order_photo_keyboard()),
        )
        return

    if incoming.photo_file_ids:
        file_id = incoming.photo_file_ids[-1]
        await state_store.update_data(product_photo_file_id=file_id)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Где вы планируете использовать UGC-видео?",
            keyboard=flow_keyboard(keyboard=content_usage_keyboard()),
        )
        await state_store.set_state(OrderCreationStates.content_usage.state)
        return

    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "Выберите «Добавить фото» или «Пропустить» на клавиатуре, "
            "либо отправьте фото продукта."
        ),
        keyboard=flow_keyboard(keyboard=order_photo_keyboard()),
    )


@router.message(OrderCreationStates.content_usage)
async def handle_content_usage(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store content usage and ask deadlines."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    text = (incoming.text or "").strip()
    if text not in (
        CONTENT_USAGE_SOCIAL,
        CONTENT_USAGE_ADS,
        CONTENT_USAGE_BOTH,
    ):
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Выберите один из вариантов на клавиатуре.",
            keyboard=flow_keyboard(keyboard=content_usage_keyboard()),
        )
        return

    content_usage_offer = CONTENT_USAGE_TO_OFFER.get(text, text)
    await state_store.update_data(content_usage=content_usage_offer)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "В какие сроки вам нужен контент? "
            "Укажите, через сколько дней после согласования "
            "вы ожидаете превью."
        ),
        keyboard=flow_keyboard(keyboard=deadlines_keyboard()),
    )
    await state_store.set_state(OrderCreationStates.deadlines.state)


@router.message(OrderCreationStates.deadlines)
async def handle_deadlines(
    message: Message,
    state: FSMContext,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Store deadlines and ask geography."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    text = (incoming.text or "").strip()
    if text not in (DEADLINES_3, DEADLINES_7, DEADLINES_14):
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Выберите один из вариантов на клавиатуре.",
            keyboard=flow_keyboard(keyboard=deadlines_keyboard()),
        )
        return

    deadlines_offer = DEADLINES_TO_OFFER.get(text, text)
    await state_store.update_data(deadlines=deadlines_offer)
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=(
            "В каких городах или регионах может находиться креатор? "
            "Можно указать от 1 до 10 городов, "
            "регионы или написать «РФ». "
            "Нужно для бартерных заказов и доставки продукта."
        ),
        keyboard=flow_keyboard_remove(),
    )
    await state_store.set_state(OrderCreationStates.geography.state)


@router.message(OrderCreationStates.geography)
async def handle_geography(
    message: Message,
    state: FSMContext,
    order_service: OrderService,
    config: AppConfig,
    contact_pricing_service: ContactPricingService,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle geography and create order."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    state_store = AiogramStateStore(state)
    geography = (incoming.text or "").strip()
    err = validate_geography(geography)
    if err is not None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=err,
            keyboard=flow_keyboard_remove(),
        )
        return

    data = await state_store.get_data()
    user_id = parse_user_id_from_state(data, key="user_id")
    if user_id is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Сессия истекла. Начните заново с «Создать заказ».",
        )
        await state_store.clear()
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

    await state_store.clear()
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=ORDER_CREATED_MESSAGE,
        parse_mode="Markdown",
    )
    contact_price = await contact_pricing_service.get_price(bloggers_needed)
    if contact_price is None or contact_price <= 0:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Стоимость доступа не настроена. Свяжитесь с поддержкой.",
        )
        return
    await send_order_invoice(
        incoming_message=incoming,
        messenger_client=messenger_client,
        order_id=order.order_id,
        offer_text=order.offer_text,
        price_value=contact_price,
        config=config,
    )
