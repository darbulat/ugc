"""Immutable policy inputs and assessments; these never apply journal money."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from ugc_bot.domain.collaboration import CollaborationState
from ugc_bot.domain.financial import MANAGEMENT_REWARD_MINOR, MAX_MINOR, utc

ACCOMPANIMENT_REFUND_STAGES = frozenset(
    state.value
    for state in CollaborationState
    if state != CollaborationState.DISPUTED
)
_ANCHORS = ("item_delivered", "order_closed")
_CLOSURES = ("all_positions_resolved", "manual")
_MANAGER_MODES = ("retain_earned", "proportional", "manual_review")
_DOCUMENT_KEYS = frozenset(
    (
        "schema_version",
        "selection_refund_window_seconds",
        "selection_refund_window_anchor",
        "selection_closure_mode",
        "accompaniment_refund_rates_bps",
        "accompaniment_manager_refund_mode",
    )
)


def _choice(value: object, allowed: tuple[str, ...]) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError("invalid_refund_rule_mode")


def _bounded_integer(value: object, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid_refund_rule_amount")


def _optional_time(value: datetime | None) -> datetime | None:
    return utc(value) if value is not None else None


def _after(at: datetime, duration: timedelta) -> datetime:
    try:
        return at + duration
    except OverflowError as error:
        raise ValueError("refund_time_out_of_range") from error


@dataclass(frozen=True, slots=True)
class AccompanimentRefundAssessment:
    """Cumulative targets, not additional refunds or applied reversals."""

    customer_refund_minor: int | None
    manager_adjustment_minor: int | None
    review_reason: str | None


@dataclass(frozen=True, slots=True)
class RefundRules:
    selection_refund_window_seconds: int
    selection_refund_window_anchor: str
    selection_closure_mode: str
    accompaniment_refund_rates_bps: tuple[tuple[str, int], ...]
    accompaniment_manager_refund_mode: str

    def __post_init__(self) -> None:
        _bounded_integer(self.selection_refund_window_seconds, 1, 31536000)
        _choice(self.selection_refund_window_anchor, _ANCHORS)
        _choice(self.selection_closure_mode, _CLOSURES)
        _choice(self.accompaniment_manager_refund_mode, _MANAGER_MODES)
        rates = self.accompaniment_refund_rates_bps
        if type(rates) is not tuple:
            raise ValueError("invalid_refund_stage_rates")
        seen: set[str] = set()
        for pair in rates:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("invalid_refund_stage_rates")
            stage, rate = pair
            if (
                not isinstance(stage, str)
                or stage not in ACCOMPANIMENT_REFUND_STAGES
                or stage in seen
            ):
                raise ValueError("invalid_refund_stage_rates")
            _bounded_integer(rate, 0, 10000)
            seen.add(stage)
        object.__setattr__(
            self, "accompaniment_refund_rates_bps", tuple(sorted(rates))
        )

    def to_document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "selection_refund_window_seconds": (
                self.selection_refund_window_seconds
            ),
            "selection_refund_window_anchor": (
                self.selection_refund_window_anchor
            ),
            "selection_closure_mode": self.selection_closure_mode,
            "accompaniment_refund_rates_bps": dict(
                self.accompaniment_refund_rates_bps
            ),
            "accompaniment_manager_refund_mode": (
                self.accompaniment_manager_refund_mode
            ),
        }

    @classmethod
    def from_document(cls, value: object) -> "RefundRules":
        if (
            type(value) is not dict
            or set(value) != _DOCUMENT_KEYS
            or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1
            or type(value.get("accompaniment_refund_rates_bps")) is not dict
        ):
            raise ValueError("invalid_refund_rules_document")
        return cls(
            selection_refund_window_seconds=value[
                "selection_refund_window_seconds"
            ],
            selection_refund_window_anchor=value[
                "selection_refund_window_anchor"
            ],
            selection_closure_mode=value["selection_closure_mode"],
            accompaniment_refund_rates_bps=tuple(
                value["accompaniment_refund_rates_bps"].items()
            ),
            accompaniment_manager_refund_mode=value[
                "accompaniment_manager_refund_mode"
            ],
        )

    def selection_closed_at(
        self,
        *,
        position_resolved_at: tuple[datetime | None, ...],
        manual_closed_at: datetime | None = None,
    ) -> datetime | None:
        """Both modes require real delivery/refund resolution for every item."""
        if type(position_resolved_at) is not tuple or not position_resolved_at:
            raise ValueError("selection_resolution_facts_required")
        times = tuple(_optional_time(at) for at in position_resolved_at)
        manual = _optional_time(manual_closed_at)
        known = tuple(at for at in times if at is not None)
        if manual is not None and known and manual < max(known):
            raise ValueError("selection_closure_before_resolution")
        if self.selection_closure_mode == "all_positions_resolved":
            if manual is not None:
                raise ValueError("manual_selection_closure_not_applicable")
            return max(known) if len(known) == len(times) else None
        return manual if len(known) == len(times) else None

    def selection_refund_deadline(
        self,
        *,
        item_delivered_at: datetime | None,
        order_closed_at: datetime | None,
    ) -> datetime | None:
        delivered = _optional_time(item_delivered_at)
        closed = _optional_time(order_closed_at)
        if delivered is not None and closed is not None and delivered > closed:
            raise ValueError("selection_closure_before_delivery")
        anchor = (
            delivered
            if self.selection_refund_window_anchor == "item_delivered"
            else closed
        )
        return (
            _after(
                anchor, timedelta(seconds=self.selection_refund_window_seconds)
            )
            if anchor is not None
            else None
        )

    def selection_available_at(
        self,
        *,
        item_delivered_at: datetime | None,
        order_closed_at: datetime | None,
    ) -> datetime | None:
        """A date assessment never proves fulfillment or authorizes a payout."""
        deadline = self.selection_refund_deadline(
            item_delivered_at=item_delivered_at,
            order_closed_at=order_closed_at,
        )
        closed = _optional_time(order_closed_at)
        if deadline is None or closed is None or item_delivered_at is None:
            return None
        return _after(max(deadline, closed), timedelta(days=14))

    def assess_accompaniment_refund(
        self, *, stage: str, paid_minor: int, manager_earned_minor: int
    ) -> AccompanimentRefundAssessment:
        """Return cumulative half-up targets under the saved contract terms."""
        if not isinstance(stage, str) or stage not in CollaborationState:
            raise ValueError("invalid_refund_work_stage")
        _bounded_integer(paid_minor, 0, MAX_MINOR // 400)
        _bounded_integer(manager_earned_minor, 0, MANAGEMENT_REWARD_MINOR)
        if (
            paid_minor != 0 and paid_minor < MANAGEMENT_REWARD_MINOR
        ) or manager_earned_minor not in (
            0,
            MANAGEMENT_REWARD_MINOR,
        ):
            raise ValueError("standard_accompaniment_amount_required")
        if paid_minor == 0 and manager_earned_minor:
            raise ValueError("funded_management_required")
        rates = dict(self.accompaniment_refund_rates_bps)
        if stage == CollaborationState.DISPUTED or stage not in rates:
            return AccompanimentRefundAssessment(
                None, None, "accompaniment_refund_review_required"
            )
        rate = rates[stage]
        customer = (paid_minor * rate + 5000) // 10000
        if customer == 0 or manager_earned_minor == 0:
            return AccompanimentRefundAssessment(customer, 0, None)
        if self.accompaniment_manager_refund_mode == "manual_review":
            return AccompanimentRefundAssessment(
                customer, None, "manager_adjustment_review_required"
            )
        manager = (
            (manager_earned_minor * rate + 5000) // 10000
            if self.accompaniment_manager_refund_mode == "proportional"
            else 0
        )
        return AccompanimentRefundAssessment(customer, manager, None)
