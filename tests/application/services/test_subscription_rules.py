from datetime import datetime, timedelta, timezone

import pytest

from ugc_bot.domain.subscriptions import SubscriptionTariff, subscription_period


@pytest.mark.parametrize(
    "field,value",
    [
        ("price_minor", True),
        ("price_minor", 0),
        ("duration_days", 0),
        ("campaign_limit", -1),
        ("recipient_limit", 0),
        ("duration_days", 366),
    ],
)
def test_unpublished_or_invalid_tariff_cannot_authorize_access(field, value):
    values = dict(
        version="pilot-v1",
        title="Manager",
        price_minor=10000,
        duration_days=30,
        campaign_limit=5,
        recipient_limit=100,
        terms_reference="terms:v1",
    )
    with pytest.raises(ValueError):
        SubscriptionTariff(**(values | {field: value}))


def test_paid_renewal_preserves_unused_period_and_expired_starts_now():
    at = datetime(2026, 10, 25, tzinfo=timezone.utc)
    assert subscription_period(at, at + timedelta(days=3), 30) == (
        at + timedelta(days=3),
        at + timedelta(days=33),
    )
    assert subscription_period(at, at - timedelta(seconds=1), 30) == (
        at,
        at + timedelta(days=30),
    )


def test_tariff_snapshot_excludes_shared_database_access():
    tariff = SubscriptionTariff("v1", "Manager", 10000, 30, 5, 100, "terms:v1")
    assert tariff.to_document()["scope"] == "own_consented_network"
    assert tariff.to_document()["price_minor"] == 10000
