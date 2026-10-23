from datetime import datetime, timedelta, timezone
from uuid import uuid4


def test_selection_and_accompaniment_components():
    from ugc_bot.application.services.paid_item_service import build_quote

    quote = build_quote(
        order_id=uuid4(),
        count=30,
        accompaniment_ordinals=frozenset({1, 3}),
        currency="RUB",
        policy_version="v1",
        selection_due_at=datetime.now(timezone.utc) + timedelta(days=2),
        client_contact_reference="protected:client",
        terms_reference="terms:v1",
        idempotency_key="quote-1",
    )
    assert len(quote.items) == 30
    assert quote.total_minor == 1740000
    assert quote.selection_base_minor == 1500000
    assert quote.items[0].selection_minor == 50000
    assert quote.items[0].accompaniment_minor == 120000
    assert quote.items[1].accompaniment_minor == 0
