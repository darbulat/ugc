"""Read-only v1 replay and explicit payout/readiness gate.

Debt means paid cancellation: V and D increase together. Evidenced recovery
increases R and decreases D. Historical paid is never rewritten. This module
neither creates bank facts nor repairs projections.
"""

from dataclasses import dataclass, field, replace
from uuid import UUID

from ugc_bot.application.financial_ports import (
    JournalMovement,
    LedgerRepository,
    ObligationBasis,
)

BUCKETS = (
    "pending",
    "hold",
    "available",
    "reserved",
    "paid",
    "cancelled",
    "blocked",
    "debt",
)
UNPAID = ("pending", "hold", "available", "reserved", "blocked")
AllocationKey = tuple[UUID, UUID]


@dataclass(frozen=True, slots=True)
class ReplayResult:
    balances: dict[str, int]
    by_obligation: dict[UUID, dict[str, int]]
    gross: int
    reversed: int
    paid: int
    recovered: int
    allocations: dict[AllocationKey, int]
    allocation_paid: dict[AllocationKey, int]
    referenced_events: tuple[JournalMovement, ...]
    errors: tuple[str, ...]

    @property
    def unpaid(self) -> int:
        return sum(self.balances[b] for b in UNPAID)

    @property
    def debt(self) -> int:
        return self.balances["debt"]

    @property
    def balanced(self) -> bool:
        return not self.errors and (
            self.gross - self.reversed - self.paid + self.recovered
            == self.unpaid - self.debt
        )


@dataclass
class _Replay:
    """One isolated accumulator, never a mutable persistence model."""

    currency: str
    by_obligation: dict[UUID, dict[str, int]] = field(default_factory=dict)
    gross: int = 0
    reversed: int = 0
    paid: int = 0
    recovered: int = 0
    allocations: dict[AllocationKey, int] = field(default_factory=dict)
    allocation_paid: dict[AllocationKey, int] = field(default_factory=dict)
    allocation_bindings: dict[UUID, tuple[UUID, UUID, str]] = field(
        default_factory=dict
    )
    references: list[JournalMovement] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    seen: dict[str, JournalMovement] = field(default_factory=dict)
    debt_totals: dict[UUID, int] = field(default_factory=dict)
    case_debt: dict[tuple[UUID, UUID | None], int] = field(default_factory=dict)

    def add(self, entry: JournalMovement) -> None:
        if entry.currency != self.currency:
            self.errors.append("mixed_currency")
            return
        previous = self.seen.get(entry.operation_key)
        if previous is not None:
            if replace(previous, recorded_at=entry.recorded_at) != entry:
                self.errors.append(
                    "operation_payload_conflict:" + entry.operation_key
                )
            return
        self.seen[entry.operation_key] = entry
        buckets = self.by_obligation.setdefault(
            entry.obligation_id, dict.fromkeys(BUCKETS, 0)
        )
        if entry.movement_type == "issuance":
            self.gross += entry.amount_minor
            buckets["pending"] += entry.amount_minor
        elif entry.movement_type == "transfer":
            self.transfer(entry, buckets)
        elif entry.movement_type == "reversal":
            self.reverse(entry, buckets)
        else:
            self.debt_or_recovery(entry, buckets)
        self.link(entry)

    def transfer(self, entry: JournalMovement, buckets: dict[str, int]) -> None:
        assert entry.bucket_from is not None and entry.bucket_to is not None
        buckets[entry.bucket_from] -= entry.amount_minor
        buckets[entry.bucket_to] += entry.amount_minor
        if entry.bucket_to == "paid":
            self.paid += entry.amount_minor
            if entry.bucket_from != "reserved":
                self.errors.append("paid_without_reserve")

    def reverse(self, entry: JournalMovement, buckets: dict[str, int]) -> None:
        if entry.bucket_from not in UNPAID or entry.bucket_to != "cancelled":
            self.errors.append("invalid_reversal_buckets")
            return
        assert entry.bucket_from is not None
        self.reversed += entry.amount_minor
        buckets[entry.bucket_from] -= entry.amount_minor
        buckets["cancelled"] += entry.amount_minor

    def debt_or_recovery(
        self, entry: JournalMovement, buckets: dict[str, int]
    ) -> None:
        if entry.bucket_from is not None or entry.bucket_to is not None:
            self.errors.append("invalid_" + entry.movement_type + "_buckets")
            return
        key = (entry.obligation_id, entry.case_id)
        if entry.movement_type == "debt":
            self.reversed += entry.amount_minor
            buckets["debt"] += entry.amount_minor
            buckets["cancelled"] += entry.amount_minor
            self.debt_totals[entry.obligation_id] = (
                self.debt_totals.get(entry.obligation_id, 0)
                + entry.amount_minor
            )
            self.case_debt[key] = (
                self.case_debt.get(key, 0) + entry.amount_minor
            )
        else:
            self.recovered += entry.amount_minor
            buckets["debt"] -= entry.amount_minor
            self.case_debt[key] = (
                self.case_debt.get(key, 0) - entry.amount_minor
            )

    def link(self, entry: JournalMovement) -> None:
        if (
            "reserved" in (entry.bucket_from, entry.bucket_to)
            or entry.bucket_to == "paid"
        ):
            self.bind_allocation(entry)
        if entry.request_id is not None and entry.allocation_id is not None:
            key = (entry.request_id, entry.allocation_id)
            self.allocations.setdefault(key, 0)
            if entry.bucket_to == "reserved":
                self.allocations[key] += entry.amount_minor
            if entry.bucket_from == "reserved":
                if self.allocations[key] < entry.amount_minor:
                    self.errors.append("allocation_exceeds_reserved")
                self.allocations[key] -= entry.amount_minor
            if entry.bucket_to == "paid":
                self.allocation_paid[key] = (
                    self.allocation_paid.get(key, 0) + entry.amount_minor
                )
        if any(
            (
                entry.request_id,
                entry.case_id,
                entry.refund_id,
                entry.source_entry_id,
            )
        ):
            self.references.append(entry)

    def bind_allocation(self, entry: JournalMovement) -> None:
        if entry.request_id is None or entry.allocation_id is None:
            self.errors.append("allocation_references_required")
            return
        binding = (entry.request_id, entry.obligation_id, entry.currency)
        previous = self.allocation_bindings.get(entry.allocation_id)
        if previous is not None and previous != binding:
            self.errors.append(
                "allocation_binding_conflict:" + str(entry.allocation_id)
            )
        elif entry.bucket_to == "reserved":
            self.allocation_bindings[entry.allocation_id] = binding
        elif previous is None:
            self.errors.append(
                "allocation_without_reserve:" + str(entry.allocation_id)
            )

    def finish(self) -> ReplayResult:
        if any(value < 0 for value in self.case_debt.values()):
            self.errors.append("recovery_exceeds_case_debt")
        for oid, buckets in self.by_obligation.items():
            if self.debt_totals.get(oid, 0) > buckets["paid"]:
                self.errors.append("debt_exceeds_historical_paid")
            if any(value < 0 for value in buckets.values()):
                self.errors.append("negative_obligation_bucket:" + str(oid))
        if any(value < 0 for value in self.allocations.values()):
            self.errors.append("negative_allocation")
        totals = {
            b: sum(o[b] for o in self.by_obligation.values()) for b in BUCKETS
        }
        return ReplayResult(
            totals,
            self.by_obligation,
            self.gross,
            self.reversed,
            self.paid,
            self.recovered,
            self.allocations,
            self.allocation_paid,
            tuple(self.references),
            tuple(self.errors),
        )


def replay_journal(
    entries: tuple[JournalMovement, ...], *, currency: str
) -> ReplayResult:
    if currency != "RUB":
        raise ValueError("unpublished_currency")
    replay = _Replay(currency)
    for entry in entries:
        replay.add(entry)
    return replay.finish()


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    recipient_id: UUID
    currency: str
    replay: ReplayResult
    differences: dict[str, tuple[int, int]]

    @property
    def payout_ready(self) -> bool:
        """Ledger consistency only, not legal/liquidity authorization."""
        return self.replay.balanced and not self.differences

    @property
    def audit_required(self) -> bool:
        return not self.payout_ready


def validate_issuance(
    entries: tuple[JournalMovement, ...],
    bases: tuple[ObligationBasis, ...],
    *,
    recipient_id: UUID,
    currency: str,
) -> tuple[str, ...]:
    """One initial issue per persisted basis; never infer money."""
    errors: list[str] = []
    expected = {basis.obligation_id: basis for basis in bases}
    if len(expected) != len(bases):
        errors.append("duplicate_obligation_basis")
    seen: set[str] = set()
    issues: dict[UUID, list[JournalMovement]] = {}
    for entry in entries:
        if entry.obligation_id not in expected:
            errors.append("unknown_obligation:" + str(entry.obligation_id))
        if entry.operation_key in seen:
            continue
        seen.add(entry.operation_key)
        if entry.movement_type == "issuance":
            issues.setdefault(entry.obligation_id, []).append(entry)
    for oid, basis in expected.items():
        if (
            basis.recipient_id != recipient_id
            or basis.currency != currency
            or type(basis.amount_minor) is not int
            or basis.amount_minor <= 0
        ):
            errors.append("invalid_obligation_basis:" + str(oid))
        recognized = issues.get(oid, [])
        if len(recognized) != 1:
            errors.append("issuance_cardinality:" + str(oid))
        elif recognized[0].amount_minor != basis.amount_minor:
            errors.append("issuance_amount:" + str(oid))
    return tuple(errors)


class FinancialReconciliationService:
    def __init__(self, repository: LedgerRepository) -> None:
        self.repository = repository

    async def reconcile(
        self, recipient_id: UUID, currency: str, *, session: object
    ) -> ReconciliationReport:
        # All reads share the wallet writer barrier until caller exit.
        await self.repository.lock_wallets(
            ((recipient_id, currency),), session=session
        )
        bases = await self.repository.list_obligation_bases(
            recipient_id, currency, session=session
        )
        entries = await self.repository.list_for_recipient(
            recipient_id, currency, session=session
        )
        replay = replay_journal(entries, currency=currency)
        replay = replace(
            replay,
            errors=replay.errors
            + validate_issuance(
                entries, bases, recipient_id=recipient_id, currency=currency
            ),
        )
        actual = await self.repository.read_projection(
            recipient_id, currency, session=session
        )
        differences = {
            b: (replay.balances[b], actual[b])
            for b in BUCKETS
            if replay.balances[b] != actual[b]
        }
        return ReconciliationReport(recipient_id, currency, replay, differences)

    async def require_ready(
        self, recipient_id: UUID, currency: str, *, session: object
    ) -> ReconciliationReport:
        # Caller rolls back on failure; never commit or repair here.
        report = await self.reconcile(recipient_id, currency, session=session)
        if not report.payout_ready:
            raise ValueError("reconciliation_mismatch_audit_required")
        return report
