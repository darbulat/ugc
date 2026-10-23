"""The real application factory wires quotes but never activates finance."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ugc_bot.config import AppConfig
from ugc_bot.container import Container


@pytest.mark.asyncio
async def test_real_container_wires_quotes_fail_closed_without_db_activity():
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": "sqlite:///:memory:",
            "KAFKA_ENABLED": False,
            "REDIS_URL": "",
        }
    )
    container = Container(config)
    try:
        services = container.build_bot_services()
        orders = services["order_service"]
        paid = orders.paid_item_service
        assert paid is not None
        assert paid.policy_service.config is config.financial
        assert not paid.policy_service.config.core_enabled
        assert not paid.policy_service.config.new_orders_enabled
        assert hasattr(paid.policy_service, "load_policy"), (
            "Approved-policy service entry missing"
        )
        with pytest.raises(ValueError, match="financial_disabled"):
            await paid.policy_service.load_policy("any-version")
        # No tables are created: disabled finance must fail before SQL, sends,
        # or creating a legacy order as a fallback.
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="financial_disabled"):
            await orders.create_financial_order(
                order_id=uuid4(),
                advertiser_id=uuid4(),
                order_type="ugc_only",
                product_link="https://example.test/product",
                offer_text="Test offer",
                barter_description=None,
                price=0,
                policy=None,
                order_created_at=now,
                now=now,
                selection_due_at=now + timedelta(days=1),
                currency="RUB",
                accompaniment_ordinals=frozenset(),
                client_contact_reference="client-agreed-test-reference",
                idempotency_key="disabled-quote-command",
            )
    finally:
        await container.dispose()
