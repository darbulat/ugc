"""Tests for referral reconciliation scheduler."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ugc_bot.domain.entities import MissingReferralIncome
from ugc_bot.referral_reconciliation_scheduler import run_loop, run_once


@pytest.mark.asyncio
async def test_run_once_records_missing_creator_income() -> None:
    """run_once should find and record missing creator income."""
    order_id = uuid4()
    creator_id = uuid4()

    missing = MissingReferralIncome(
        order_id=order_id,
        referred_user_id=creator_id,
        advertiser_country_code="ru",
        income_type="creator",
    )

    income_repo = MagicMock()
    income_repo.find_missing_creator_income = AsyncMock(return_value=[missing])
    income_repo.find_missing_advertiser_income = AsyncMock(return_value=[])

    order = MagicMock()
    order.order_id = order_id
    order_repo = MagicMock()
    order_repo.get_by_id = AsyncMock(return_value=order)

    recorder = MagicMock()
    recorder.record_creator_referral_income = AsyncMock()
    recorder.record_advertiser_referral_income = AsyncMock()

    count = await run_once(income_repo, recorder, order_repo, None)

    assert count == 1
    recorder.record_creator_referral_income.assert_called_once_with(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
        session=None,
    )


@pytest.mark.asyncio
async def test_run_once_records_missing_advertiser_income() -> None:
    """run_once should find and record missing advertiser income."""
    order_id = uuid4()
    advertiser_id = uuid4()

    missing = MissingReferralIncome(
        order_id=order_id,
        referred_user_id=advertiser_id,
        advertiser_country_code="us",
        income_type="advertiser",
    )

    income_repo = MagicMock()
    income_repo.find_missing_creator_income = AsyncMock(return_value=[])
    income_repo.find_missing_advertiser_income = AsyncMock(
        return_value=[missing]
    )

    order = MagicMock()
    order.order_id = order_id
    order_repo = MagicMock()
    order_repo.get_by_id = AsyncMock(return_value=order)

    recorder = MagicMock()
    recorder.record_creator_referral_income = AsyncMock()
    recorder.record_advertiser_referral_income = AsyncMock()

    count = await run_once(income_repo, recorder, order_repo, None)

    assert count == 1
    recorder.record_advertiser_referral_income.assert_called_once_with(
        order=order,
        advertiser_id=advertiser_id,
        advertiser_country_code="us",
        session=None,
    )


@pytest.mark.asyncio
async def test_run_once_no_missing_returns_zero() -> None:
    """run_once should return 0 when nothing is missing."""
    income_repo = MagicMock()
    income_repo.find_missing_creator_income = AsyncMock(return_value=[])
    income_repo.find_missing_advertiser_income = AsyncMock(return_value=[])
    order_repo = MagicMock()
    recorder = MagicMock()

    count = await run_once(income_repo, recorder, order_repo, None)
    assert count == 0


@pytest.mark.asyncio
async def test_run_once_skips_missing_order() -> None:
    """run_once should skip if order not found in repo."""
    missing = MissingReferralIncome(
        order_id=uuid4(),
        referred_user_id=uuid4(),
        advertiser_country_code="ru",
        income_type="creator",
    )

    income_repo = MagicMock()
    income_repo.find_missing_creator_income = AsyncMock(return_value=[missing])
    income_repo.find_missing_advertiser_income = AsyncMock(return_value=[])

    order_repo = MagicMock()
    order_repo.get_by_id = AsyncMock(return_value=None)

    recorder = MagicMock()
    recorder.record_creator_referral_income = AsyncMock()

    count = await run_once(income_repo, recorder, order_repo, None)
    assert count == 0
    recorder.record_creator_referral_income.assert_not_called()


@pytest.mark.asyncio
async def test_run_once_continues_on_error() -> None:
    """run_once should continue processing if one record fails."""
    order_id1 = uuid4()
    order_id2 = uuid4()

    missing1 = MissingReferralIncome(
        order_id=order_id1,
        referred_user_id=uuid4(),
        advertiser_country_code="ru",
        income_type="creator",
    )
    missing2 = MissingReferralIncome(
        order_id=order_id2,
        referred_user_id=uuid4(),
        advertiser_country_code="ru",
        income_type="creator",
    )

    income_repo = MagicMock()
    income_repo.find_missing_creator_income = AsyncMock(
        return_value=[missing1, missing2]
    )
    income_repo.find_missing_advertiser_income = AsyncMock(return_value=[])

    order1 = MagicMock()
    order1.order_id = order_id1
    order2 = MagicMock()
    order2.order_id = order_id2

    order_repo = MagicMock()
    order_repo.get_by_id = AsyncMock(side_effect=[order1, order2])

    recorder = MagicMock()
    recorder.record_creator_referral_income = AsyncMock(
        side_effect=[Exception("DB timeout"), None]
    )

    count = await run_once(income_repo, recorder, order_repo, None)
    # First failed, second succeeded
    assert count == 1


@pytest.mark.asyncio
async def test_run_once_skips_missing_advertiser_order() -> None:
    """run_once should skip advertiser entry if order not found."""
    missing = MissingReferralIncome(
        order_id=uuid4(),
        referred_user_id=uuid4(),
        advertiser_country_code="us",
        income_type="advertiser",
    )

    income_repo = MagicMock()
    income_repo.find_missing_creator_income = AsyncMock(return_value=[])
    income_repo.find_missing_advertiser_income = AsyncMock(
        return_value=[missing]
    )

    order_repo = MagicMock()
    order_repo.get_by_id = AsyncMock(return_value=None)

    recorder = MagicMock()
    recorder.record_advertiser_referral_income = AsyncMock()

    count = await run_once(income_repo, recorder, order_repo, None)
    assert count == 0
    recorder.record_advertiser_referral_income.assert_not_called()


@pytest.mark.asyncio
async def test_run_once_continues_on_advertiser_error() -> None:
    """run_once should continue if advertiser recording fails."""
    oid1 = uuid4()
    oid2 = uuid4()

    missing1 = MissingReferralIncome(
        order_id=oid1,
        referred_user_id=uuid4(),
        advertiser_country_code="us",
        income_type="advertiser",
    )
    missing2 = MissingReferralIncome(
        order_id=oid2,
        referred_user_id=uuid4(),
        advertiser_country_code="us",
        income_type="advertiser",
    )

    income_repo = MagicMock()
    income_repo.find_missing_creator_income = AsyncMock(return_value=[])
    income_repo.find_missing_advertiser_income = AsyncMock(
        return_value=[missing1, missing2]
    )

    order1 = MagicMock()
    order1.order_id = oid1
    order2 = MagicMock()
    order2.order_id = oid2

    order_repo = MagicMock()
    order_repo.get_by_id = AsyncMock(side_effect=[order1, order2])

    recorder = MagicMock()
    recorder.record_advertiser_referral_income = AsyncMock(
        side_effect=[Exception("fail"), None]
    )

    count = await run_once(income_repo, recorder, order_repo, None)
    assert count == 1


@pytest.mark.asyncio
@patch(
    "ugc_bot.referral_reconciliation_scheduler"
    ".install_asyncio_exception_handler"
)
async def test_run_loop_runs_max_iterations(
    mock_handler,
) -> None:
    """run_loop should stop after max_iterations."""
    income_repo = MagicMock()
    income_repo.find_missing_creator_income = AsyncMock(return_value=[])
    income_repo.find_missing_advertiser_income = AsyncMock(return_value=[])
    recorder = MagicMock()
    order_repo = MagicMock()

    iterations = await run_loop(
        income_entry_repo=income_repo,
        recorder=recorder,
        order_repo=order_repo,
        transaction_manager=None,
        interval_seconds=0,
        max_iterations=3,
    )

    assert iterations == 3
