from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from tests.application.services.test_financial_policy_service import (
    ready_policy,
)
from ugc_bot.infrastructure.db.repositories.entitlements import (
    SqlAlchemyClientEntitlementRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import (
    SqlAlchemyFinancialCaptureRepository,
)
from ugc_bot.infrastructure.db.repositories.selection_delivery_funding import (
    SqlAlchemySelectionFundingRepository,
)


@pytest.mark.parametrize(
    "repository",
    [
        SqlAlchemyClientEntitlementRepository,
        SqlAlchemySelectionFundingRepository,
    ],
)
def test_repository_accepts_public_policy_for_non_pilot_customer(repository):
    _, pilot, args = ready_policy()
    policy = replace(pilot, all_clients=True, allowed_clients=frozenset())
    now = args["captured_at"]
    order = {"created_at": now, "advertiser_id": uuid4()}
    repository._require_policy(
        policy, now - timedelta(seconds=1), order, [], now
    )


@pytest.mark.asyncio
async def test_issued_invoice_capture_accepts_public_policy():
    gate, pilot, args = ready_policy()
    policy = replace(pilot, all_clients=True, allowed_clients=frozenset())
    now = args["captured_at"]
    order = SimpleNamespace(
        financial_version=policy.version, advertiser_id=uuid4(), created_at=now
    )
    db = SimpleNamespace(get=AsyncMock(return_value=object()))
    with patch(
        "ugc_bot.infrastructure.db.repositories.financial_capture.decode_policy_version",
        return_value=policy,
    ):
        await SqlAlchemyFinancialCaptureRepository(gate)._policy(
            db, order, [], now, issuing=False
        )
