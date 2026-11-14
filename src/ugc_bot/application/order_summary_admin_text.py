"""Plain-text notifications for automatic order summary reviews."""

from collections import Counter
from collections.abc import Mapping

from ugc_bot.domain.order_display import public_order_number

_REVIEW_REASONS = {
    "delivery_unconfirmed": "Доставка сообщения креатору не подтверждена",
    "replacement_reserve_empty": "В резерве нет подтверждённого креатора",
    "replacement_reserve_limit_reached": "Лимит автоматических замен исчерпан",
    "replacement_requires_financial_review": "Нужно проверить условия замены",
}
_DEADLINE_REASON = "contact_or_refund_unconfirmed"


def is_order_summary_review(source: Mapping) -> bool:
    payload = source.get("payload")
    return (
        source.get("kind") == "support"
        and isinstance(payload, Mapping)
        and payload.get("topic") == "order_summary"
    )


def order_summary_admin_text(source: Mapping) -> str:
    order_id = source["order_id"]
    order_number = public_order_number(order_id) if order_id else "—"
    reports = source["payload"].get("reports")
    reasons = {
        str(report["paid_item_id"]): report.get("reason")
        for report in (reports if isinstance(reports, list) else [])
        if isinstance(report, Mapping) and report.get("paid_item_id")
    }
    counts = Counter(
        "Передача контакта или полный возврат за подбор не подтверждены"
        if reason == _DEADLINE_REASON
        else _REVIEW_REASONS.get(str(reason), "Нужна проверка специалиста")
        for reason in reasons.values()
    )
    heading = (
        "Истёк срок подбора"
        if reasons
        and all(reason == _DEADLINE_REASON for reason in reasons.values())
        else "Итоги заказа требуют проверки"
    )
    lines = [f"{heading} · {order_number}", "Автоматическое уведомление."]
    lines.extend(f"{count} поз. · {label}" for label, count in counts.items())
    lines.extend(("", f"Обращение #{source['request_id']}"))
    return "\n".join(lines)
