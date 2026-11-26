"""Render the private Telegram card for a business order."""

import html
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ugc_bot.application.geography import parse_geography
from ugc_bot.domain.entities import AdvertiserProfile, Order, User
from ugc_bot.domain.enums import OrderStatus, OrderType

_ORDER_TYPES = {
    OrderType.STORIES: "Сторис",
    OrderType.UGC_PLUS_PLACEMENT: "UGC + размещение",
    OrderType.UGC_ONLY: "UGC-видео для бренда",
}


def order_card_url(value: str | None) -> str | None:
    url = (value or "").strip()
    if (
        not url
        or len(url) > 2048
        or any(
            char.isspace() or ord(char) < 32 or char in '<>"\\' for char in url
        )
    ):
        return None
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and (parsed.port is None or parsed.port > 0)
        ):
            return url
    except ValueError:
        pass
    return None


def _telegram_contact(advertiser: User | None) -> str | None:
    if advertiser is None:
        return None
    handle = (advertiser.telegram or "").strip().removeprefix("@")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", handle):
        return f'<a href="https://t.me/{handle}">@{handle}</a>'
    telegram_id = (advertiser.telegram_id or "").strip()
    if re.fullmatch(r"[1-9][0-9]{0,15}", telegram_id):
        return f'<a href="tg://user?id={telegram_id}">Открыть профиль</a>'
    return None


def _clip(value: str, limit: int) -> str:
    encoded = value.encode("utf-16-le")
    if len(encoded) <= 2 * limit:
        return value
    return (
        encoded[: 2 * (limit - 1)].decode("utf-16-le", "ignore").rstrip() + "…"
    )


def _line(label: str, value: str, limit: int = 80) -> str:
    clean = _clip(" ".join(value.split()), limit)
    return f"<b>{label}</b> · {html.escape(clean)}"


def _money(amount: Decimal, symbol: str) -> str:
    whole, _, fraction = f"{amount:,.2f}".replace(",", " ").partition(".")
    fraction = fraction.rstrip("0")
    return f"{whole},{fraction} {symbol}" if fraction else f"{whole} {symbol}"


def _manager_line(details: Mapping[str, Any], symbol: str) -> str:
    count = details.get("accompaniment_count")
    if count is None:
        manager = "не указан"
    elif count == 0:
        manager = "не нужен · самостоятельная работа"
    elif count == details.get("position_count"):
        manager = "нужен для всех креаторов"
    elif (positions := details.get("position_count")) is not None:
        manager = f"нужен для {count} из {positions}"
    else:
        manager = "нужен"
    accompaniment = details.get("accompaniment_minor", 0)
    if accompaniment:
        manager += f" · {_money(Decimal(accompaniment) / 100, symbol)}"
    return _line("Менеджер", manager)


def _quote_lines(details: Mapping[str, Any], symbol: str) -> list[str]:
    lines = [_manager_line(details, symbol)]
    if due := details.get("selection_due_at"):
        local = datetime.fromisoformat(due).astimezone(
            ZoneInfo("Europe/Moscow")
        )
        lines.append(
            _line("Срок подбора", local.strftime("%d.%m.%Y, %H:%M МСК"))
        )
    if (selection := details.get("selection_base_minor")) is not None:
        lines.append(_line("Подбор", _money(Decimal(selection) / 100, symbol)))
    consultation = details.get("consultation_minor") or 0
    if consultation:
        payment = (
            "оплачена"
            if details.get("consultation_state") == "paid"
            else "ожидает оплаты"
        )
        amount = _money(Decimal(consultation) / 100, symbol)
        lines.append(
            _line(
                "Консультация",
                f"{amount} · {payment} · до 60 минут на запуск, ТЗ"
                " и подбор блогеров",
                110,
            )
        )
    if (total := details.get("total_minor")) is not None:
        lines.append(
            _line(
                "Счёт за услуги",
                _money(Decimal(total + consultation) / 100, symbol),
            )
        )
    return lines


class _VisibleText(HTMLParser):
    units = 0

    def handle_data(self, data: str) -> None:
        self.units += len(data.encode("utf-16-le")) // 2


def _heading(
    order: Order,
    paid_event: bool,
    payment_confirmed: bool | None,
    *,
    consultation_unpaid: bool,
) -> str:
    moderation = order.status == OrderStatus.PENDING_MODERATION
    if paid_event:
        state = "Подбор оплачен" if consultation_unpaid else "Заказ оплачен"
        return f"<b>✅ {state}</b>" + ("\nЖдёт модерации" if moderation else "")
    if payment_confirmed:
        state = "Подбор оплачен" if consultation_unpaid else "Оплачен"
        payment = f"✅ {state}" + (" · ждёт модерации" if moderation else "")
    elif order.complimentary:
        payment = "⚪ Без оплаты по согласованию"
    elif order.status == OrderStatus.NEW:
        payment = "🟠 Ожидает оплаты"
    elif payment_confirmed is False:
        payment = "🟠 Оплата не получена"
    else:
        payment = "⚪ Статус оплаты неизвестен"
    return f"<b>📋 Новый заказ от бизнеса</b>\n{payment}"


def _client_lines(
    advertiser: User | None,
    profile: AdvertiserProfile | None,
    reference: str | None,
) -> list[str]:
    name = (
        advertiser.username
        if advertiser and advertiser.username
        else "Не указан"
    )
    client = [_line("Заказчик", name, 55)]
    if contact := _telegram_contact(advertiser):
        client.append(f"<b>Telegram</b> · {contact}")
    if profile and (profile.phone or "").strip():
        client.append(_line("Телефон", profile.phone, 35))
    if reference and not reference.strip().lower().startswith(
        ("telegram:", "max:")
    ):
        client.append(_line("Доп. контакт", reference, 65))

    return client


def business_order_geography(value: str | None) -> str:
    geography = (value or "").strip()
    spec = parse_geography(geography)
    if (
        not geography
        or (spec and spec.type == "world")
        or geography.lower()
        in {"любом", "любой город", "в любом городе", "без ограничений"}
    ):
        return "Любой город"
    return geography


def business_order_type(order: Order) -> str:
    return _ORDER_TYPES[order.order_type]


def _terms_lines(
    order: Order, symbol: str, eligible_count: int | None
) -> list[str]:
    terms = [
        _line("Формат", business_order_type(order)),
        _line("Бюджет на автора", _money(Decimal(str(order.price)), symbol)),
        _line("Бартер", (order.barter_description or "").strip() or "нет"),
        _line("Креаторов нужно", str(order.bloggers_needed)),
        _line("География", business_order_geography(order.geography), 65),
    ]
    if eligible_count is not None:
        terms.append(_line("Потенциально подходят", str(eligible_count)))
    # Let the admin panel carry the full text of unusually large fields.
    if order.deadlines and order.deadlines.strip():
        terms.append(_line("Сроки контента", order.deadlines, 65))
    if order.content_usage and order.content_usage.strip():
        terms.append(_line("Использование контента", order.content_usage, 65))

    return terms


def render_business_order_card(
    order: Order,
    *,
    advertiser: User | None,
    profile: AdvertiserProfile | None,
    symbol: str,
    details: Mapping[str, Any] | None,
    payment_confirmed: bool | None,
    paid_event: bool,
    eligible_count: int | None,
    flagged: bool,
) -> str:
    details = details or {}
    consultation_unpaid = bool(details.get("consultation_minor")) and (
        details.get("consultation_state") != "paid"
    )
    sections = [
        _heading(
            order,
            paid_event,
            payment_confirmed,
            consultation_unpaid=consultation_unpaid,
        ),
        "\n".join(
            _client_lines(advertiser, profile, details.get("contact_reference"))
        ),
        "\n".join(_terms_lines(order, symbol, eligible_count)),
        "\n".join(_quote_lines(details, symbol)),
    ]
    if flagged:
        sections.insert(1, "⚠️ <b>Возможен запрещённый контент</b>")

    overview = "\n\n".join(sections)
    description = re.sub(
        r"\n{3,}",
        "\n\n",
        "\n".join(
            line.strip() for line in (order.offer_text or "").splitlines()
        ).strip(),
    )
    if not description:
        return overview
    prefix = overview + "\n\n<b>Задача</b>\n"
    rendered = _VisibleText()
    rendered.feed(prefix)
    limit = 1024 if order.product_photo_file_id else 4096
    remaining = limit - rendered.units
    if remaining <= 1:
        return overview
    brief = html.escape(_clip(description, remaining))
    return f"{prefix}<blockquote expandable>{brief}</blockquote>"
