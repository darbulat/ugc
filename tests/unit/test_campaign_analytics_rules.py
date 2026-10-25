"""Attribution is explicit evidence; absent observations never imply zero."""

import importlib
from datetime import datetime, timedelta, timezone

import pytest

AT = datetime(2026, 10, 25, tzinfo=timezone.utc)


def module():
    return importlib.import_module("ugc_bot.domain.campaign_analytics")


def test_no_data_and_unfinalized_import_do_not_publish_fabricated_rates():
    assert (
        module().analytics_report([], [], complete=False)["state"] == "no_data"
    )
    report = module().analytics_report(
        [
            {
                "marketing_spend_minor": 10000,
                "metrics": ["views", "clicks", "leads", "sales"],
            }
        ],
        [],
        complete=False,
    )
    assert report["state"] == "partial" and report["rates"]["cpv"] is None


def test_confirmed_costs_use_actual_counts_and_net_paid_sales():
    rows = [
        {
            "kind": "view",
            "quantity": 100,
            "entity_id": "video",
            "amount_minor": 0,
        },
        {
            "kind": "lead",
            "quantity": 1,
            "entity_id": "lead-1",
            "amount_minor": 0,
        },
        {
            "kind": "sale",
            "quantity": 1,
            "entity_id": "sale-1",
            "amount_minor": 10000,
        },
        {
            "kind": "refund",
            "quantity": 1,
            "entity_id": "sale-1",
            "amount_minor": 10000,
        },
    ]
    report = module().analytics_report(
        [
            {
                "marketing_spend_minor": 10000,
                "metrics": ["views", "clicks", "leads", "sales"],
            }
        ],
        rows,
        complete=True,
    )
    assert report["rates"] == {
        "cpv": "1.000000",
        "cpl": "100.000000",
        "cpa": None,
    }
    assert report["counts"]["paid_sales"] == 0


@pytest.mark.parametrize("quantity", [True, 0, -1, 1.1])
def test_import_rejects_ambiguous_or_nonpositive_event_counts(quantity):
    with pytest.raises(ValueError):
        module().MetricEvent("event", "view", AT, "video", quantity, 0)


def test_event_time_and_refund_amount_need_real_typed_evidence():
    with pytest.raises(ValueError):
        module().MetricEvent(
            "event", "sale", AT.replace(tzinfo=None), "sale", 1, 100
        )
    with pytest.raises(ValueError):
        module().MetricEvent("event", "refund", AT, "sale", 1, 0)


def test_incomplete_metric_coverage_and_orphan_refunds_suppress_costs():
    sources = [
        {"marketing_spend_minor": 10000, "metrics": ["views", "sales"]},
        {"marketing_spend_minor": 10000, "metrics": ["sales"]},
    ]
    report = module().analytics_report(
        sources,
        [
            {
                "kind": "view",
                "quantity": 100,
                "entity_id": "v",
                "amount_minor": 0,
            }
        ],
        complete=True,
    )
    assert report["rates"]["cpv"] is None
    report = module().analytics_report(
        sources,
        [
            {
                "kind": "refund",
                "quantity": 1,
                "entity_id": "orphan",
                "amount_minor": 100,
            }
        ],
        complete=True,
    )
    assert report["state"] == "review_required"
    assert report["rates"]["cpa"] is None


@pytest.mark.parametrize(
    "changed",
    [
        {"subject_type": "person"},
        {"subject_id": None},
        {"source_name": " "},
        {"account_label": "x" * 129},
        {"attribution_until": AT - timedelta(days=3)},
        {"currency": "JPY"},
        {"metrics": ()},
        {"marketing_spend_minor": True},
    ],
)
def test_published_source_requires_typed_scope_currency_window_and_evidence(
    changed,
):
    from uuid import uuid4

    values = dict(
        subject_type="campaign",
        subject_id=uuid4(),
        source_name="source",
        account_label="account",
        attribution_from=AT - timedelta(days=2),
        attribution_until=AT - timedelta(days=1),
        marketing_spend_minor=10000,
        currency="RUB",
        metrics=("views",),
        proof_reference="proof",
        budget_reference="budget",
        reason="reviewed",
    )
    with pytest.raises(ValueError):
        module().AnalyticsSourceSpec(**(values | changed))


@pytest.mark.parametrize(
    "values",
    [
        ("unknown", "entity", 1, 0),
        ("lead", "entity", 2, 0),
        ("view", "entity", 1, 1),
    ],
)
def test_event_semantics_reject_counts_or_amounts_without_declared_meaning(
    values,
):
    kind, entity, quantity, amount = values
    with pytest.raises(ValueError):
        module().MetricEvent("event", kind, AT, entity, quantity, amount)
