"""Explicit marketing observations; never infer spend from platform charges."""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from ugc_bot.domain.financial import utc

METRICS = frozenset(("views", "clicks", "leads", "sales"))
TWO_DECIMAL_CURRENCIES = frozenset(("RUB", "USD", "EUR", "KZT", "BYN", "UZS"))


def required(value, maximum=2048):
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > maximum
    ):
        raise ValueError("analytics_evidence_required")
    return value


def event_time(value):
    try:
        return utc(value)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("analytics_event_time_required") from None


def integer(value, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("analytics_integer_required")


@dataclass(frozen=True, slots=True)
class AnalyticsSourceSpec:
    subject_type: str
    subject_id: UUID
    source_name: str
    account_label: str
    attribution_from: datetime
    attribution_until: datetime
    marketing_spend_minor: int
    currency: str
    metrics: tuple[str, ...]
    proof_reference: str
    budget_reference: str
    reason: str

    def __post_init__(self):
        if (
            self.subject_type not in ("campaign", "order")
            or not isinstance(self.subject_id, UUID)
            or self.subject_id.int == 0
        ):
            raise ValueError("analytics_subject_required")
        for name in (
            "source_name",
            "account_label",
            "proof_reference",
            "budget_reference",
            "reason",
        ):
            required(
                getattr(self, name),
                128 if name in ("source_name", "account_label") else 2048,
            )
        if event_time(self.attribution_from) >= event_time(
            self.attribution_until
        ):
            raise ValueError("analytics_attribution_window_required")
        integer(self.marketing_spend_minor)
        if self.currency not in TWO_DECIMAL_CURRENCIES:
            raise ValueError("analytics_currency_required")
        if (
            type(self.metrics) is not tuple
            or not self.metrics
            or set(self.metrics) - METRICS
        ):
            raise ValueError("analytics_metric_coverage_required")
        object.__setattr__(self, "metrics", tuple(sorted(set(self.metrics))))

    def document(self):
        return {
            "subject_type": self.subject_type,
            "subject_id": str(self.subject_id),
            "source_name": self.source_name,
            "account_label": self.account_label,
            "attribution_from": utc(self.attribution_from).isoformat(),
            "attribution_until": utc(self.attribution_until).isoformat(),
            "marketing_spend_minor": self.marketing_spend_minor,
            "currency": self.currency,
            "metrics": list(self.metrics),
            "proof_reference": self.proof_reference,
            "budget_reference": self.budget_reference,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class MetricEvent:
    external_event_id: str
    kind: str
    occurred_at: datetime
    entity_id: str
    quantity: int = 1
    amount_minor: int = 0

    def __post_init__(self):
        required(self.external_event_id, 256)
        required(self.entity_id, 256)
        event_time(self.occurred_at)
        if self.kind not in ("view", "click", "lead", "sale", "refund"):
            raise ValueError("analytics_event_kind_required")
        integer(self.quantity, 1, 10**9)
        integer(self.amount_minor)
        if self.kind in ("lead", "sale", "refund") and self.quantity != 1:
            raise ValueError("analytics_distinct_entity_required")
        if self.kind in ("sale", "refund"):
            if self.amount_minor == 0:
                raise ValueError("analytics_paid_amount_required")
        elif self.amount_minor:
            raise ValueError("analytics_event_amount_not_applicable")

    def document(self):
        return {
            "external_event_id": self.external_event_id,
            "kind": self.kind,
            "occurred_at": utc(self.occurred_at).isoformat(),
            "entity_id": self.entity_id,
            "quantity": self.quantity,
            "amount_minor": self.amount_minor,
        }


def analytics_report(sources, events, *, complete):
    spend = sum(source["marketing_spend_minor"] for source in sources)
    coverage = set().union(*(set(s["metrics"]) for s in sources))
    full_coverage = {
        metric
        for metric in METRICS
        if sources and all(metric in s["metrics"] for s in sources)
    }
    sales, refunds = {}, {}
    for event in events:
        if event["kind"] == "sale":
            sales[event["entity_id"]] = event["amount_minor"]
        elif event["kind"] == "refund":
            key = event["entity_id"]
            refunds[key] = refunds.get(key, 0) + event["amount_minor"]
    review_required = any(
        entity not in sales or amount > sales[entity]
        for entity, amount in refunds.items()
    )
    complete = complete and not review_required
    counts = {
        "views": sum(e["quantity"] for e in events if e["kind"] == "view"),
        "clicks": sum(e["quantity"] for e in events if e["kind"] == "click"),
        "leads": len({e["entity_id"] for e in events if e["kind"] == "lead"}),
        "paid_sales": sum(
            amount > refunds.get(entity, 0) for entity, amount in sales.items()
        ),
    }
    rates = {}
    for metric, count, covered in (
        ("cpv", "views", "views"),
        ("cpl", "leads", "leads"),
        ("cpa", "paid_sales", "sales"),
    ):
        denominator = counts[count]
        rates[metric] = (
            str(
                (Decimal(spend) / Decimal(100) / denominator).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP
                )
            )
            if complete and sources and covered in full_coverage and denominator
            else None
        )
    return {
        "state": "no_data"
        if not sources
        else "review_required"
        if review_required
        else "complete"
        if complete
        else "partial",
        "metric_coverage": sorted(full_coverage),
        "marketing_spend_minor": str(spend) if sources else None,
        "counts": {
            key: value
            if sources and ("sales" if key == "paid_sales" else key) in coverage
            else None
            for key, value in counts.items()
        },
        "rates": rates,
        "net_sales_revenue_minor": str(
            sum(
                amount - refunds.get(entity, 0)
                for entity, amount in sales.items()
            )
        )
        if "sales" in coverage and not review_required
        else None,
    }
