"""Unexpected payout boundary failures cannot echo private values."""

import httpx
import pytest
from fastapi import APIRouter, FastAPI

from ugc_bot.miniapp.payout_api import NoStorePayoutRoute


def test_source_and_private_proof_failures_have_exact_safe_translation():
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofConflict,
        PhysicalProofUnavailable,
    )
    from ugc_bot.miniapp.payout_api import failure

    source = failure(ValueError("payout_bank_source_configuration_required"))
    assert source.status_code == 409
    assert source.detail == "payout_bank_source_configuration_required"
    for private in (PhysicalProofConflict(), PhysicalProofUnavailable()):
        result = failure(private)
        assert result.status_code == 503
        assert result.detail == "payout_unavailable"


@pytest.mark.asyncio
async def test_unexpected_failure_is_private_and_uncacheable(caplog):
    app = FastAPI()
    router = APIRouter(route_class=NoStorePayoutRoute)
    private = "SYNTHETIC-PRIVATE-EXCEPTION-PAYLOAD"

    @router.post("/synthetic-boundary")
    async def broken():
        raise ValueError(private)

    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/synthetic-boundary")
    assert response.status_code == 503
    assert response.json() == {"detail": "payout_unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert private not in response.text + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("path", ["/request", "/operations/status"])
@pytest.mark.parametrize(
    "private",
    ["SYNTHETIC_PRIVATE_SERVICE_FAILURE", "payout_private_synthetic_failure"],
)
async def test_signed_service_value_error_cannot_escape_boundary(
    config, caplog, platform, path, private
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from tests.e2e.miniapp_helpers import generate_init_data
    from ugc_bot.config import MaxBotConfig
    from ugc_bot.miniapp.api import router

    actor = uuid4()
    service = SimpleNamespace(
        execute=AsyncMock(side_effect=ValueError(private)),
        operation_for_actor=AsyncMock(side_effect=ValueError(private)),
    )

    class Transactions:
        @asynccontextmanager
        async def transaction(self):
            yield object()

    roles = SimpleNamespace(
        get_user=AsyncMock(
            return_value=SimpleNamespace(
                user_id=actor, telegram_id="12345", max_id="12345", country="ru"
            )
        )
    )
    config.financial.core_enabled = config.financial.payouts_enabled = True
    config.max_bot = MaxBotConfig(MAX_BOT_TOKEN="synthetic-max-token")
    token = (
        config.bot.bot_token if platform == "telegram" else config.max_bot.token
    )
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = config
    app.state.dispatcher = dict(
        user_role_service=roles,
        transaction_manager=Transactions(),
        payout_service=service,
    )
    auth = generate_init_data(token, 12345, "Synthetic signed owner")
    body = dict(
        init_data=auth, platform=platform, operation_key="service-failure"
    )
    if path == "/request":
        body.update(requisites_id=str(uuid4()), amount_minor="1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/miniapp/api/payouts" + path, json=body)
    assert response.status_code == 503
    assert response.json() == {"detail": "payout_unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert private not in response.text + caplog.text
    assert auth not in response.text + caplog.text
    roles.get_user.assert_awaited_once()
    method = (
        service.execute if path == "/request" else service.operation_for_actor
    )
    method.assert_awaited_once()


@pytest.mark.asyncio
async def test_safety_and_masked_reasons_exclude_unexpected_failure_text():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from ugc_bot.application.services.payout_service import PayoutService

    private = "SYNTHETIC_PRIVATE_CAUGHT_FAILURE"
    actor, request, requirement, requisites = (uuid4() for _ in range(4))
    repo = SimpleNamespace(
        allocations=AsyncMock(return_value=[]),
        lock_users=AsyncMock(),
        user=AsyncMock(return_value={"status": "active", "admin": False}),
        requirements_lock=AsyncMock(),
        latest_requirements=AsyncMock(
            return_value={"requirements_id": requirement, "enabled": True}
        ),
        contracts=SimpleNamespace(
            accepted_contract=AsyncMock(side_effect=ValueError(private)),
            own_requisites=AsyncMock(
                return_value=[
                    dict(
                        requisites_id=requisites,
                        requirements_id=requirement,
                        requirements_version=1,
                        recorded_at=datetime.now(timezone.utc),
                        masked_label="••••1234",
                    )
                ]
            ),
        ),
    )
    service = PayoutService(
        repo,
        None,
        None,
        SimpleNamespace(now=lambda: datetime.now(timezone.utc)),
        SimpleNamespace(core_enabled=True, payouts_enabled=True),
    )
    service._clear = AsyncMock(side_effect=ValueError(private))
    reason = await service._safety_reason(
        dict(
            request_id=request, recipient_id=actor, requirements_id=requirement
        ),
        [],
        session=object(),
    )
    masked = await service.requisites_for_actor(actor, session=object())
    assert reason == "payout_unavailable"
    assert "payout_unavailable" in masked[0]["unusable_reasons"]
    assert private not in str(masked) + reason
    assert not masked[0]["usable"]


def test_safe_domain_codes_are_exact_and_legacy_type_is_bounded():
    from ugc_bot.application.errors import LegacyPayoutBlockedError
    from ugc_bot.application.payout_errors import (
        PUBLIC_PAYOUT_CODES,
        public_payout_code,
    )
    from ugc_bot.miniapp.payout_api import failure

    forbidden = {
        "financial_principal_changed",
        "active_actor_required",
        "active_admin_required",
        "payout_own_or_admin_required",
        "payout_own_requisites_required",
    }
    for code in PUBLIC_PAYOUT_CODES:
        response = failure(ValueError(code))
        assert response.detail == code
        assert response.status_code == (403 if code in forbidden else 409)
    assert (
        public_payout_code(LegacyPayoutBlockedError("private"))
        == "legacy_payout_blocked"
    )
    assert (
        failure(LegacyPayoutBlockedError("private")).detail
        == "legacy_payout_blocked"
    )
    for value in (
        "payout_fake_secret",
        "work_disputed private suffix",
        "private",
        "",
    ):
        response = failure(ValueError(value))
        assert (
            response.status_code == 503
            and response.detail == "payout_unavailable"
        )
