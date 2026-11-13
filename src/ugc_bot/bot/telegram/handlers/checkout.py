"""All v1 bot payment entries use the same stored Mini App checkout."""

from dataclasses import replace

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.telegram.handlers.order_controls import (
    payment_help_button,
    payment_help_keyboard,
)
from ugc_bot.domain.checkout import CheckoutActor
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.messenger.telegram.invoice_links import (
    TelegramInvoiceLinks,
)

COPY = {
    "ru": (
        (
            "Ссылка на оплату сохранённого заказа UMC. Гонорар "
            "автору оплачивается напрямую."
        ),
        "Оплатить услуги UMC",
        "Сейчас оплата недоступна. Если нужна помощь, напишите нам.",
        "Оплата услуг UMC подтверждена Telegram.",
    ),
    "en": (
        "Payment link for saved UMC order. Creator fees are paid directly.",
        "Pay for UMC services",
        "Payment is unavailable right now. Contact us if you need help.",
        "Telegram confirmed payment for UMC services.",
    ),
    "kk": (
        (
            "Сақталған UMC тапсырысының төлем сілтемесі. Автор "
            "ақысы тікелей төленеді."
        ),
        "UMC қызметтерін төлеу",
        "Төлем әзірге қолжетімсіз. Көмек қажет болса, бізге жазыңыз.",
        "Telegram UMC қызметтерінің төлемін растады.",
    ),
    "be": (
        (
            "Спасылка на аплату захаванага заказу UMC. Ганарар "
            "аўтару аплачваецца напрамую."
        ),
        "Аплаціць паслугі UMC",
        "Аплата пакуль недаступная. Калі патрэбна дапамога, напішыце нам.",
        "Telegram пацвердзіў аплату паслуг UMC.",
    ),
    "uz": (
        (
            "Saqlangan UMC buyurtmasi uchun to‘lov havolasi. "
            "Muallif haqi bevosita to‘lanadi."
        ),
        "UMC xizmatlarini to‘lash",
        "To‘lov hozir mavjud emas. Yordam kerak bo‘lsa, bizga yozing.",
        "Telegram UMC xizmatlari to‘lovini tasdiqladi.",
    ),
}


async def send_checkout_if_v1(
    order_id,
    user,
    incoming,
    origin,
    messenger,
    payments,
    checkout,
    config,
    locale,
):
    order = await payments.get_order(order_id)
    if order is None or not isinstance(order.financial_version, str):
        return False
    if order.advertiser_id != user.user_id:
        return False
    copy = COPY.get(locale, COPY["ru"])
    help_keyboard = payment_help_keyboard(order_id, locale)
    try:
        if checkout is None:
            raise ValueError("checkout_unavailable")
        if incoming.user.messenger_type != MessengerType.TELEGRAM:
            raise PermissionError("telegram_checkout_required")
        gateway = TelegramInvoiceLinks(
            origin.bot,
            config.bot.telegram_provider_token,
            config.market.receipt_service_description,
        )
        result = await replace(checkout, gateway=gateway).request_invoice(
            order_id,
            CheckoutActor(user.user_id, "telegram", incoming.user.external_id),
            f"bot-checkout:{order_id}",
        )
    except (PermissionError, ValueError, LookupError, OrderCreationError):
        await messenger.send_text(
            chat_id=incoming.chat_id, text=copy[2], keyboard=help_keyboard
        )
        return True
    if result.get("capture_state") == "confirmed":
        await messenger.send_text(chat_id=incoming.chat_id, text=copy[3])
    elif result.get("can_open") and result.get("invoice_state") == "ready":
        await messenger.send_text(
            chat_id=incoming.chat_id,
            text=copy[0],
            keyboard=Keyboard(
                kind=KeyboardKind.INLINE,
                rows=[
                    [Button(text=copy[1], url=result["invoice_url"])],
                    [payment_help_button(order_id, locale)],
                ],
            ),
        )
    else:
        await messenger.send_text(
            chat_id=incoming.chat_id, text=copy[2], keyboard=help_keyboard
        )
    return True
