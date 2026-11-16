"""Human-readable cards keep customer data within messenger limits."""

from uuid import uuid4

import pytest

from ugc_bot.application.customer_request_admin_text import (
    customer_request_admin_pages,
)
from ugc_bot.domain.customer_workflows import SupportInput


@pytest.mark.parametrize(
    ("state", "label"),
    [
        ("unpaid", "не оплачено"),
        ("processing", "обрабатывается, подтверждения пока нет"),
        ("paid", "оплата подтверждена"),
        (None, "статус неизвестен"),
    ],
)
def test_payment_card_uses_a_snapshot_label(state, label):
    (message,) = customer_request_admin_pages(
        dict(
            kind="support",
            request_id=uuid4(),
            order_id=uuid4(),
            payload={
                "topic": "payment",
                "payment_state": state,
                "contact_reference": "@client",
                "reason": "Не открывается оплата",
                "operation_key": "internal-deduplication-key",
            },
        )
    )
    assert message.split("\n\n")[1] == "Не открывается оплата"
    assert f"Оплата на момент обращения: {label}" in message
    assert "internal-deduplication-key" not in message
    assert "Вложение" not in message and "ID автора" not in message


def test_long_support_card_keeps_description_and_clickable_attachment_links():
    rid, oid, blogger = uuid4(), uuid4(), uuid4()
    reason = "😕" * 3999 + "!"
    attachments = [
        {
            "label": f"Скриншот {index}",
            "reference": f"https://example.test/{index}/" + "a" * 2000,
        }
        for index in range(10)
    ]
    saved = SupportInput(
        order_id=oid,
        operation_key="private-operation-key",
        reason=reason,
        contact_reference="@client",
        blogger_id=blogger,
        attachments=attachments,
    ).model_dump(mode="json")
    messages = customer_request_admin_pages(
        dict(kind="support", request_id=rid, order_id=oid, payload=saved)
    )
    assert len(messages) > 1
    for index, message in enumerate(messages, 1):
        header = f"💬 Обращение №{rid.hex[:8].upper()}"
        assert message.startswith(f"{header} · часть {index}/{len(messages)}")
        assert len(message.encode("utf-16-le")) // 2 < 4000
    body = "\n".join(message.split("\n\n", 1)[1] for message in messages)
    assert f"ID автора: {blogger}" in body
    description = body.split("Заказ:")[0]
    assert description.replace("\n", "") == reason
    for attachment in attachments:
        assert any(attachment["reference"] in message for message in messages)
    assert "private-operation-key" not in body
