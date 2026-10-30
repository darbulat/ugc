"""A public policy supersedes pilot only for newly created orders."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from tests.postgres_financial.test_order_intake import intake_env, service
from tests.postgres_financial.test_order_intake_api import app, body
from ugc_bot.application.services.checkout_service import CheckoutService
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyService,
)
from ugc_bot.domain.checkout import CheckoutActor
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel
from ugc_bot.infrastructure.db.repositories.checkout import (
    SqlCheckoutRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import (
    SqlAlchemyFinancialCaptureRepository,
)
from ugc_bot.public_policy_from_pilot import (
    PUBLIC_URL,
    PUBLIC_VERSION,
    SOURCE_VERSION,
)

__all__ = ["intake_env"]


@pytest.mark.asyncio
async def test_pilot_cutover_rejects_new_api_order_but_replays_existing(
    intake_env,
):
    env = intake_env
    now = env["clock"].at
    with Session(env["pg"]) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=SOURCE_VERSION,
                approved_by=env["admin"].user_id,
                approved_at=now - timedelta(days=2),
                effective_from=now - timedelta(days=1),
                refund_window_seconds=604800,
                rules={
                    "allowed_clients": [str(env["user"].user_id)],
                    "terms_reference": "https://example.test/pilot",
                },
            )
        )
        db.add(
            FinancialPolicyVersionModel(
                version=PUBLIC_VERSION,
                approved_by=env["admin"].user_id,
                approved_at=now,
                effective_from=now + timedelta(hours=1),
                refund_window_seconds=604800,
                rules={
                    "allowed_clients": [],
                    "all_clients": True,
                    "maturity_mode": "per_item_v1",
                    "selection_refund_window_anchor": (
                        "per_item_delivery_accepted_at"
                    ),
                    "hold_seconds": 1209600,
                    "terms_reference": PUBLIC_URL,
                    "refund_rules": RefundRules(
                        604800, "item_delivered", "manual", (), "manual_review"
                    ).to_document(),
                },
            )
        )
    env["policy"] = SOURCE_VERSION
    application = app(env, env["container"])
    application.state.dispatcher["order_intake_service"] = service(env)
    payload = body(env)
    auth = {key: payload[key] for key in ("init_data", "platform")}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        listing = await client.post(
            "/miniapp/api/financial/orders/policies", json=auth
        )
        assert SOURCE_VERSION in {
            p["version"] for p in listing.json()["policies"]
        }
        first = await client.post("/miniapp/api/financial/orders", json=payload)
        assert first.status_code == 200, first.text

        env["clock"].at = now + timedelta(hours=1)
        listing = await client.post(
            "/miniapp/api/financial/orders/policies", json=auth
        )
        versions = {p["version"] for p in listing.json()["policies"]}
        assert PUBLIC_VERSION in versions
        assert SOURCE_VERSION not in versions
        duplicate = await client.post(
            "/miniapp/api/financial/orders", json=payload
        )
        assert duplicate.status_code == 200 and duplicate.json() == first.json()
        config = env["config"].model_copy(
            update={
                "bot": env["config"].bot.model_copy(
                    update={
                        "telegram_provider_token": "synthetic-provider",
                        "telegram_payment_account_id": "synthetic-account",
                    }
                )
            }
        )
        checkout = CheckoutService(
            SqlCheckoutRepository(
                config,
                SqlAlchemyFinancialCaptureRepository(
                    FinancialPolicyService(config.financial)
                ),
            ),
            env["container"].transaction_manager,
            SimpleNamespace(
                create_link=AsyncMock(
                    return_value="https://t.me/$synthetic_actual_link"
                )
            ),
            True,
            True,
        )
        invoice = await checkout.request_invoice(
            UUID(first.json()["order_id"]),
            CheckoutActor(
                env["user"].user_id, "telegram", env["user"].telegram_id
            ),
            "prior-pilot-order",
        )
        assert invoice["invoice_state"] == "ready"
        assert invoice["amount_minor"] == first.json()["total_minor"]
        new_order = await client.post(
            "/miniapp/api/financial/orders",
            json=payload | {"operation_key": "stale-pilot:" + uuid4().hex},
        )
        assert new_order.status_code == 409
        assert new_order.json()["detail"] == "pilot_policy_superseded"
        public = await client.post(
            "/miniapp/api/financial/orders",
            json=payload
            | {
                "operation_key": "new-public:" + uuid4().hex,
                "policy_version": PUBLIC_VERSION,
            },
        )
        assert public.status_code == 200, public.text
        assert public.json()["policy_version"] == PUBLIC_VERSION
