"""Plain-text admin cards for customer support and service requests."""

from collections.abc import Iterator, Mapping

from ugc_bot.domain.customer_workflows import CATALOG, customer_request_number
from ugc_bot.domain.order_display import public_order_number

_PAYMENT_STATES = {
    "unpaid": "не оплачено",
    "processing": "обрабатывается, подтверждения пока нет",
    "paid": "оплата подтверждена",
}
_SERVICES = {row["code"]: row["title"] for row in CATALOG}
_SERVICE_FIELDS = {
    "name": "Имя",
    "telegram": "Telegram",
    "company": "Компания",
    "niche": "Ниша",
    "product": "Продукт",
    "expected_benefit": "Ожидаемый результат",
    "website": "Сайт",
    "geography": "География",
    "average_check": "Средний чек",
    "margin_or_cac": "Маржа или стоимость привлечения клиента",
    "current_sales": "Текущие продажи",
    "goal": "Цель",
    "tracking": "Как измеряется результат",
}
# Reserve room for the heading and the link to the admin order. Count UTF-16
# units so emoji and other supplementary characters fit both providers' limits.
_PAGE_BODY_LIMIT = 3600


def message_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _field(lines: list[str], label: str, value: object) -> None:
    if isinstance(value, str) and value.strip():
        lines.append(f"{label}: {value}")


def _support_lines(lines: list[str], payload: Mapping) -> None:
    if payload.get("topic") == "payment":
        _field(
            lines,
            "Оплата на момент обращения",
            _PAYMENT_STATES.get(
                str(payload.get("payment_state")), "статус неизвестен"
            ),
        )
    _field(lines, "ID автора", payload.get("blogger_id"))
    _field(lines, "Что произошло", payload.get("reason"))
    attachments = payload.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if isinstance(attachment, Mapping):
                _field(
                    lines,
                    f"Вложение ({attachment.get('label') or 'ссылка'})",
                    attachment.get("reference"),
                )


def _service_lines(lines: list[str], payload: Mapping) -> None:
    _field(
        lines,
        "Услуга",
        _SERVICES.get(str(payload.get("service_code")), "Требует уточнения"),
    )
    parameters = payload.get("parameters")
    if isinstance(parameters, Mapping):
        for key, label in _SERVICE_FIELDS.items():
            _field(lines, label, parameters.get(key))


def _line_fragments(line: str) -> Iterator[str]:
    if message_units(line) <= _PAGE_BODY_LIMIT:
        yield line
        return
    # Only split inside a line when it could not fit on its own page.
    start = size = 0
    for index, char in enumerate(line):
        width = 2 if ord(char) > 0xFFFF else 1
        if size + width > _PAGE_BODY_LIMIT:
            yield line[start:index]
            start, size = index, 0
        size += width
    yield line[start:]


def _bodies(lines: list[str]) -> list[str]:
    pages: list[str] = []
    pending: list[str] = []
    size = 0
    for line in "\n".join(lines).split("\n"):
        for piece in _line_fragments(line):
            width = message_units(piece)
            if pending and size + 1 + width > _PAGE_BODY_LIMIT:
                pages.append("\n".join(pending))
                pending, size = [], 0
            size += width + bool(pending)
            pending.append(piece)
    return [*pages, "\n".join(pending)]


def customer_request_admin_pages(source: Mapping) -> list[str]:
    payload = source["payload"]
    support = source["kind"] == "support"
    number = customer_request_number(source["request_id"])
    if support:
        heading = f"Обращение №{number}"
        if payload.get("topic") == "payment":
            heading = f"Проблема с оплатой · {heading}"
    else:
        heading = f"Заявка на услугу №{number}"
    lines: list[str] = []
    if order_id := source["order_id"]:
        lines.append(f"Заказ: {public_order_number(order_id)}")
    _field(lines, "Контакт клиента", payload.get("contact_reference"))
    (_support_lines if support else _service_lines)(lines, payload)
    pages = _bodies(lines)
    if len(pages) == 1:
        return [f"{heading}\n\n{pages[0]}" if pages[0] else heading]
    return [
        f"{heading} · часть {index}/{len(pages)}\n\n{page}"
        for index, page in enumerate(pages, 1)
    ]
