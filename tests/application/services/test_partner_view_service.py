"""Current grade never reprices historical money or hides missing sources."""

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from ugc_bot.application.financial_ports import JournalMovement
from ugc_bot.application.partner_view_ports import (
    PartnerFinancialFacts,
    PartnerMovement,
    PartnerObligation,
    PartnerReadFacts,
)
from ugc_bot.application.services.partner_view_service import PartnerViewService

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)
ACTOR = UUID(int=1)


class Repository:
    def __init__(self, facts):
        self.facts = facts

    async def read(
        self,
        actor_id,
        at,
        *,
        network_page,
        assignment_page,
        session,
        principal=None,
    ):
        return self.facts


def facts():
    return PartnerReadFacts(
        ACTOR, "active", "abcd1234", 0, 0, (), None, None, None, None
    )


async def view(value, **kwargs):
    service = PartnerViewService(
        Repository(value),
        SimpleNamespace(now=lambda: NOW),
        {"telegram": "synthetic_bot", "max": "synthetic_max"},
    )
    return await service.view(
        ACTOR,
        platform="telegram",
        writes_paused=True,
        session=object(),
        **kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "count,rate,next_count,remaining",
    [
        (0, 1000, 100, 100),
        (99, 1000, 100, 1),
        (100, 1200, 200, 100),
        (199, 1200, 200, 1),
        (200, 1500, 400, 200),
        (399, 1500, 400, 1),
        (400, 2000, None, None),
    ],
)
async def test_grade_counts_verified_creators_at_exact_published_boundaries(
    count, rate, next_count, remaining
):
    result = await view(replace(facts(), verified_creators=count))
    assert result["grade"]["tier_rate_bps"] == rate
    assert result["grade"]["next_threshold"] == next_count
    assert result["grade"]["remaining"] == remaining
    assert result["standards"]["client_first_year_bps"] == 1000
    assert result["standards"]["after_year_bps"] == 300


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,error",
    [
        (None, LookupError),
        (replace(facts(), actor_id=UUID(int=2)), PermissionError),
        (replace(facts(), account_status="blocked"), PermissionError),
        (replace(facts(), account_status="deleted"), PermissionError),
    ],
)
async def test_partner_rejects_missing_or_foreign_or_blocked_source(
    value, error
):
    with pytest.raises(error):
        await view(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [-1, True, 100001])
async def test_partner_rejects_unbounded_or_noninteger_pages(page):
    with pytest.raises(ValueError, match="invalid_partner_page"):
        await view(facts(), network_page=page)


def financial():
    obligations, movements = [], []
    for n, kind, amount in (
        (10, "client_referral", 5000),
        (11, "creator_referral", 10000),
        (12, "management", 60000),
    ):
        obligations.append(
            PartnerObligation(
                UUID(int=n),
                kind,
                UUID(int=20),
                UUID(int=n + 20),
                None,
                amount,
                amount if kind == "management" else amount * 10,
                None if kind == "management" else 1000,
                "standard",
                "historical-approved-v1",
                NOW,
                None if kind == "management" else NOW,
                None if kind != "creator_referral" else 0,
            )
        )
        movement = JournalMovement(
            obligation_id=UUID(int=n),
            operation_key=f"issue:{n}",
            event_id=f"event:{n}",
            movement_type="issuance",
            amount_minor=amount,
            currency="RUB",
            effective_at=NOW,
            recorded_at=NOW,
            actor_id=ACTOR,
            reason="PRIVATE CASE",
            bucket_to="pending",
        )
        movements.append(PartnerMovement(UUID(int=n + 100), movement))
    return PartnerFinancialFacts(
        tuple(obligations),
        tuple(movements),
        {
            "pending": 75000,
            "hold": 0,
            "available": 0,
            "reserved": 0,
            "paid": 0,
            "cancelled": 0,
            "blocked": 0,
            "debt": 0,
        },
    )


@pytest.mark.asyncio
async def test_separate_kinds_and_new_grade_cannot_reprice_snapshots():
    result = await view(
        replace(facts(), verified_creators=400, financial=financial())
    )
    assert result["grade"]["tier_rate_bps"] == 2000
    money = result["financial"]
    assert money["state"] == "ready" and money["balances"]["pending"] == "75000"
    assert {r["kind"]: r["balances"]["pending"] for r in money["groups"]} == {
        "client_referral": "5000",
        "creator_referral": "10000",
        "management": "60000",
    }
    assert {r["kind"]: r["rate_bps"] for r in money["history"]["entries"]} == {
        "client_referral": 1000,
        "creator_referral": 1000,
        "management": None,
    }
    assert "PRIVATE CASE" not in str(result)


@pytest.mark.asyncio
async def test_missing_wallet_with_journal_is_a_reconciliation_problem():
    result = await view(
        replace(facts(), financial=replace(financial(), projection=None))
    )
    assert result["financial"]["state"] == "mismatch"
    assert result["financial"]["projection"] is None
    assert result["financial"]["balances"]["pending"] == "75000"


@pytest.mark.asyncio
async def test_unavailable_sources_never_turn_into_zeros_or_legacy_pending():
    result = await view(facts())
    assert result["financial"]["state"] == "unavailable"
    assert result["financial"]["balances"] is None
    assert result["overrides"] == {"state": "unavailable", "entries": ()}
    assert result["assignments"]["total"] is None


@pytest.mark.asyncio
async def test_invalid_configured_referral_link_is_unavailable():
    service = PartnerViewService(
        Repository(facts()),
        SimpleNamespace(now=lambda: NOW),
        {"telegram": "bad.example/?inject=1"},
    )
    result = await service.view(
        ACTOR, platform="telegram", writes_paused=True, session=object()
    )
    assert result["referral"]["link"] is None
