"""A fixed management fee is not a referral percentage or an age/grade."""

from dataclasses import replace
from uuid import uuid4

import pytest

from tests.application.services.test_financial_ledger_service import (
    MemoryLedger,
    command,
)
from ugc_bot.application.financial_ports import IssuedObligation
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)


def management_basis(**changes):
    basis = replace(
        command(),
        kind="management",
        assignment_id=uuid4(),
        base_minor=60_000,
        registered_at=None,
        verified_count=None,
        rate_bps=None,
        available_at=None,
    )
    return replace(basis, **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [1, 59_999, 60_001, 120_000])
async def test_new_management_issue_rejects_nonstandard_reward_without_mutation(
    amount,
):
    import copy

    basis = management_basis(base_minor=amount)
    repo = MemoryLedger()
    before = copy.deepcopy(vars(repo))
    with pytest.raises(ValueError, match="unapproved_management_reward"):
        await FinancialLedgerService(repo).issue(
            basis, recorded_at=basis.snapshot_at, session=object()
        )
    assert vars(repo) == before


@pytest.mark.asyncio
async def test_fixed_fee_uses_no_referral_age_rate_or_grade():
    basis = management_basis()
    repo = MemoryLedger()
    service = FinancialLedgerService(repo)
    result = await service.issue(
        basis, recorded_at=basis.snapshot_at, session=object()
    )
    assert isinstance(result, IssuedObligation)
    assert result.movement.amount_minor == 60_000
    assert result.movement.bucket_to == "pending"
    assert result.basis.registered_at is None
    assert result.basis.verified_count is None
    assert result.basis.rate_bps is None


def test_management_basis_requires_real_assignment_identity():
    with pytest.raises(ValueError, match="management_assignment_required"):
        management_basis(assignment_id=None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rate_bps", 10000),
        ("verified_count", 0),
        ("registered_at", command().snapshot_at),
    ],
)
def test_management_basis_rejects_inapplicable_referral_fields(field, value):
    with pytest.raises(
        ValueError, match="management_referral_fields_not_applicable"
    ):
        management_basis(**{field: value})
