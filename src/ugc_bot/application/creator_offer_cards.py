"""Public offer and response cards for newly created orders."""

import re
from dataclasses import dataclass
from decimal import Decimal
from html import escape, unescape
from urllib.parse import urlsplit

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderType, RejectionReason

CALLBACK_PREFIX = "offer_card:"
NEUTRAL_COVER = "ugc:neutral-offer-cover"
CAPTION_LIMIT = 1024
PUBLIC_FIELDS = {
    "sender_name": 64,
    "title": 64,
    "task": 200,
    "brief": 620,
    "deadline": 106,
    "usage": 106,
    "barter": 100,
    "brand": 64,
}
CONTACT_FIELDS = ("contact", "client_contact", "manager_contact")
COMMUNICATION_ROLES = {"client", "manager"}


def offer_contact(card: dict[str, str]) -> str | None:
    """Resolve only the selected role; never expose the other party."""
    role = card.get("communication_role")
    if role:
        return (
            card.get(f"{role}_contact") if role in COMMUNICATION_ROLES else None
        )
    return card.get("contact")


_IDENTIFYING_LINK = re.compile(
    r"@|://|www\.|(?<!\w)[\w-]+\.(?:app|com|net|org|ru|рф|me|io)\b"
    r"|(?<!\d)\+?\d[\d ()-]{8,}\d",
    re.IGNORECASE,
)
_TELEGRAM_HANDLE = re.compile(r"@?([a-zA-Z][a-zA-Z0-9_]{4,31})\Z")


@dataclass(frozen=True)
class OfferCard:
    text: str
    keyboard: Keyboard | None


def telegram_contact_url(handle: str | None) -> str | None:
    match = _TELEGRAM_HANDLE.fullmatch((handle or "").strip())
    return f"https://t.me/{match[1]}" if match else None


def https_link(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or any(char.isspace() for char in text):
        return None
    try:
        url = urlsplit(text if "://" in text else f"https://{text}")
        if (
            url.scheme in ("https", "http")
            and url.hostname
            and "." in url.hostname
            and url.username is None
            and url.port in (None, 80, 443)
        ):
            return url.geturl()
    except ValueError:
        pass
    return None


def validate_public_offer(
    card: dict[str, str], *, ready: bool = False, barter: bool = False
) -> dict[str, str]:
    """Validate only the fields explicitly supplied for publication."""
    result = {}
    for key, limit in PUBLIC_FIELDS.items():
        value = (card.get(key) or "").strip()
        if len(value.encode("utf-16-le")) // 2 > limit:
            raise ValueError(
                f"Поле карточки «{key}» слишком длинное ({limit})."
            )
        if _IDENTIFYING_LINK.search(value):
            raise ValueError("Уберите ссылки и контакты из публичной карточки.")
        if value:
            result[key] = value
    result.update(_validated_contacts(card, ready=ready))
    if card.get("photo") == "approved":
        result["photo"] = "approved"
    required = {"title", "task", "deadline", "usage"}
    if barter:
        required.add("barter")
    if ready and not required <= result.keys():
        raise ValueError(
            "Заполните заголовок, задачу, срок и использование в карточке "
            "креатора. Для бартера укажите его условия."
        )
    return result


def _validated_contacts(card: dict[str, str], *, ready: bool) -> dict[str, str]:
    result = {}
    for key in CONTACT_FIELDS:
        contact = (card.get(key) or "").strip()
        if contact:
            if telegram_contact_url(contact) is None:
                raise ValueError(
                    "Укажите рабочий Telegram в формате @username."
                )
            result[key] = contact
    role = (card.get("communication_role") or "").strip()
    if role:
        if role not in COMMUNICATION_ROLES:
            raise ValueError("Выберите, кто общается: заказчик или менеджер.")
        result["communication_role"] = role
        selected_contact = offer_contact(result)
        if ready and not selected_contact:
            raise ValueError("Укажите Telegram выбранного ответственного.")
        # Keep older app replicas on the same contact during a rolling release.
        result.pop("contact", None)
        if selected_contact:
            result["contact"] = selected_contact
    return result


_FORMAT = {
    OrderType.UGC_ONLY: ("UGC-видео", "UGC video"),
    OrderType.UGC_PLUS_PLACEMENT: ("Видео + публикация", "Video + placement"),
    OrderType.STORIES: ("Сторис", "Stories"),
}
_REASONS = {
    "price": (RejectionReason.LOW_PRICE, "Низкая цена", "Low pay"),
    "format": (
        RejectionReason.WRONG_FORMAT,
        "Формат не подходит",
        "Wrong format",
    ),
    "time": (RejectionReason.NO_TIME, "Нет времени", "No time"),
    "product": (
        RejectionReason.UNINTERESTING_PRODUCT,
        "Не мой продукт",
        "Not a fit",
    ),
    "brand": (
        RejectionReason.ALREADY_WORKING_WITH_BRAND,
        "Уже работаю с брендом",
        "Already working with the brand",
    ),
}
SKIP_REASONS = {code: reason[0] for code, reason in _REASONS.items()}
VIEWS = {"open", "brief", "safe", "confirm", "skip"}


def _ru(locale: str) -> bool:
    return locale.lower().replace("_", "-").split("-", 1)[0] == "ru"


def reward(order: Order, ru: bool) -> str:
    if order.price <= 0:
        return "Бартер" if ru else "Barter"
    amount = Decimal(str(order.price))
    precision = 0 if amount == amount.to_integral_value() else 2
    number = f"{amount:,.{precision}f}".replace(",", "\u202f")
    if ru:
        number = number.replace(".", ",")
    currency = "₽" if order.currency == "RUB" else order.currency
    return f"{number} {currency}"


def _state_content(
    order: Order, card: dict[str, str], view: str, ru: bool
) -> tuple[str, list[str]]:
    title = card["title"]
    if view == "open":
        lines = [
            f"<b>{escape(reward(order, ru))}</b> · "
            + _FORMAT.get(order.order_type, _FORMAT[OrderType.UGC_ONLY])[
                not ru
            ],
            "",
            escape(card["task"]),
            "",
            ("<b>Срок</b> · " if ru else "<b>Deadline</b> · ")
            + escape(card["deadline"]),
            ("<b>Где используют</b> · " if ru else "<b>Use</b> · ")
            + escape(card["usage"]),
        ]
        if card.get("sender_name"):
            lines.insert(
                0,
                ("<b>Заказчик</b> · " if ru else "<b>Client</b> · ")
                + escape(card["sender_name"]),
            )
        if card.get("barter") and order.price > 0:
            lines.append(
                ("<b>Бартер</b> · " if ru else "<b>Barter</b> · ")
                + escape(card["barter"])
            )
        elif card.get("barter"):
            lines.insert(1, escape(card["barter"]))
        if card.get("brand"):
            lines.append(
                ("<b>Бренд</b> · " if ru else "<b>Brand</b> · ")
                + escape(card["brand"])
            )
        return title, lines
    if view == "brief":
        return ("Короткий бриф" if ru else "Brief"), [
            escape(card.get("brief") or card["task"])
        ]
    variants = {
        "safe": (
            "Безопасная работа",
            "Согласуй условия напрямую. Покажи превью с водяным знаком. "
            "Передай финал после оплаты. Откликайся, если условия подходят. "
            "Отказ при прежних условиях может привести к жалобе.",
            "Work safely",
            "Agree on terms directly. Share a watermarked preview and deliver "
            "the final version after payment. Apply if the terms suit you.",
        ),
        "confirm": (
            "Подтверди отклик",
            "Подтверждая отклик, ты соглашаешься с условиями. "
            "Заказчик получит твой профиль и доступный контакт.",
            "Confirm your response",
            "Confirm to accept the terms and share your profile and contact.",
        ),
        "skip": (
            "Почему пропускаешь?",
            "Выбери причину.",
            "Why skip?",
            "Choose a reason.",
        ),
        "skipped": ("Оффер пропущен", "", "Offer skipped", ""),
        "reserve": (
            "Ты в листе ожидания",
            "Подборка уже заполнена.",
            "You’re on the waitlist",
            "The current selection is full.",
        ),
        "closed": (
            "Заказ закрыт",
            "Отклики больше не принимаются.",
            "Order closed",
            "This order is no longer accepting responses.",
        ),
    }
    headline, detail = variants[view][0:2] if ru else variants[view][2:4]
    if view == "confirm":
        return headline, [escape(reward(order, ru)), "", detail]
    return headline, [detail] if detail else []


def _keyboard(order: Order, view: str, ru: bool) -> Keyboard | None:
    def action(label: str, code: str) -> Button:
        return Button(
            label,
            callback_data=f"{CALLBACK_PREFIX}{code}:{order.order_id}",
            style="primary" if code in {"confirm", "done"} else None,
        )

    apply = action("Откликнуться" if ru else "Respond", "confirm")
    back = action("← К офферу" if ru else "← Back", "open")
    brief = action("Бриф" if ru else "Brief", "brief")
    safety = action("Правила" if ru else "Rules", "safe")
    rows = {
        "open": [
            [apply],
            [brief, safety, action("Пропустить" if ru else "Skip", "skip")],
        ],
        "brief": [[apply], [back]],
        "safe": [[back]],
        "confirm": [
            [
                action(
                    "Подтвердить отклик" if ru else "Confirm response", "done"
                )
            ],
            [brief, back],
        ],
        "skip": [
            *[
                [action(labels[1 if ru else 2], f"s_{code}")]
                for code, labels in _REASONS.items()
            ],
            [back],
        ],
    }.get(view)
    return Keyboard(KeyboardKind.INLINE, rows) if rows else None


def render_public_offer(
    order: Order, locale: str, view: str = "open"
) -> OfferCard:
    card = validate_public_offer(
        order.creator_offer_card or {}, ready=True, barter=order.price <= 0
    )
    ru = _ru(locale)
    heading, lines = _state_content(order, card, view, ru)
    text = "\n".join([f"<b>{escape(heading)}</b>", "", *lines]).rstrip()
    # The generated markup has only bold tags. Count its decoded text in
    # UTF-16, including dynamic fields, ahead of any provider call.
    visible_text = unescape(text.replace("<b>", "").replace("</b>", ""))
    if len(visible_text.encode("utf-16-le")) // 2 > CAPTION_LIMIT:
        raise ValueError("Карточка не помещается в одно сообщение Telegram.")
    return OfferCard(text, _keyboard(order, view, ru))


def render_saved_offer(order: Order, locale: str) -> OfferCard:
    ru = _ru(locale)
    card = order.creator_offer_card or {}
    contact = telegram_contact_url(offer_contact(card))
    if contact:
        next_step = (
            "Рабочий контакт по заказу доступен ниже."
            if ru
            else "The work contact is available below."
        )
    else:
        next_step = (
            "Заказчик напишет первым."
            if ru
            else "The client will reach out first."
        )
    title = "Отклик сохранён" if ru else "Response saved"
    brief = https_link(order.brief_link)
    product = https_link(order.product_link)
    links = [
        Button(label, url=url, style="primary" if url == contact else None)
        for label, url in (
            (
                "Написать по заказу" if ru else "Message about the order",
                contact,
            ),
            ("Продукт" if ru else "Product", product),
            ("Полное ТЗ" if ru else "Full brief", brief),
        )
        if url
    ]
    rules = (
        "Покажи превью с водяным знаком. Передай финал после оплаты."
        if ru
        else "Use a watermarked preview. Deliver the final after payment."
    )
    body = (
        f"<b>{title}</b>\n\n{escape(card['title'])} · "
        f"{escape(reward(order, ru))}\n{next_step}\n\n{rules}"
    )
    keyboard = Keyboard(KeyboardKind.INLINE, [[link] for link in links])
    return OfferCard(body, keyboard if links else None)


def client_contact_links(
    *, profile: str, handle: str | None, locale: str
) -> tuple[tuple[str, str], ...]:
    ru = _ru(locale)
    write = telegram_contact_url(handle)
    links = (
        [("Написать креатору" if ru else "Message creator", write)]
        if write
        else []
    )
    links.append(("Открыть профиль" if ru else "Open profile", profile))
    return tuple(links)


def client_contact_text(
    *, order_title: str, name: str, phone: str | None, locale: str
) -> str:
    ru = _ru(locale)
    lines = [
        "Новый отклик" if ru else "New response",
        order_title,
        "",
        name or ("Креатор" if ru else "Creator"),
    ]
    if phone:
        lines.append(("Телефон" if ru else "Phone") + " · " + phone)
    lines.extend(
        [
            "",
            "Напишите креатору, чтобы согласовать съёмку."
            if ru
            else "Message the creator to agree on the shoot.",
            "Оплачивайте после просмотра превью с водяным знаком."
            if ru
            else "Pay after reviewing the watermarked preview.",
        ]
    )
    return "\n".join(lines)
