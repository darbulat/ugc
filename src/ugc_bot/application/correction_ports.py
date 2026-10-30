"""Bounded correction commands and trusted caller-transaction interfaces.

Principal proof is the frozen native principal, supplied separately from all
economic commands and hashes. Every source/assessment below is server-loaded.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.application.entitlement_ports import ClientCapture
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.corrections import (
    COMPONENTS,
    Component,
    ComponentFunding,
    CorrectionEvent,
    CorrectionState,
    SelectionRefundBundle,
    correction_payload_hash,
    require_currency,
    require_hash,
    require_minor,
    require_text,
    require_uuid,
    require_version,
    uuid_tuple,
)
from ugc_bot.domain.financial import MAX_MINOR, commission_minor, utc

CorrectionPrincipal = AuthenticatedMessengerPrincipal


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionActor:
    user_id: UUID
    telegram_id: str | None
    max_id: str | None
    status: str
    admin: bool

    def __post_init__(self) -> None:
        require_uuid(self.user_id)
        require_text(self.status, 64)
        if type(self.admin) is not bool:
            raise ValueError("correction_actor_invalid")
        for value in (self.telegram_id, self.max_id):
            if value is not None:
                require_text(value, 128)


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionReadAuthority:
    """Only immutable owner/action routing, never private receipt contents."""

    current_client_id: UUID | None
    case_client_id: UUID | None = None
    case_order_id: UUID | None = None
    request_client_id: UUID | None = None
    request_order_id: UUID | None = None
    action: str | None = None

    def __post_init__(self) -> None:
        for value in (
            self.current_client_id,
            self.case_client_id,
            self.case_order_id,
            self.request_client_id,
            self.request_order_id,
        ):
            if value is not None:
                require_uuid(value)
        if self.action is not None:
            require_text(self.action, 64)


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionFact:
    """An immutable copied SQL fact; JSON is storage, never caller authority.

    Reading data returns a fresh deep value. Source eligibility still comes
    from the trusted complete CorrectionScope and exact relational checks.
    """

    kind: str
    payload_json: str

    def __post_init__(self) -> None:
        if self.kind not in (
            "cases",
            "requests",
            "intents",
            "observations",
            "matches",
            "approvals",
            "match_approvals",
            "events",
            "commands",
            "payments",
            "invoice",
        ):
            raise ValueError("correction_fact_invalid")
        if (
            not isinstance(self.payload_json, str)
            or len(self.payload_json) > 262144
        ):
            raise ValueError("correction_fact_invalid")
        value = json.loads(self.payload_json)
        if type(value) is not dict or self.payload_json != self._encode(value):
            raise ValueError("correction_fact_invalid")

    @staticmethod
    def _encode(value):
        return json.dumps(
            canonical(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def from_values(
        cls, kind: str, values: Mapping[str, object]
    ) -> CorrectionFact:
        return cls(kind=kind, payload_json=cls._encode(dict(values)))

    @property
    def data(self):
        return json.loads(self.payload_json)


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionFacts:
    records: tuple[CorrectionFact, ...] = ()

    def __post_init__(self) -> None:
        if type(self.records) is not tuple or any(
            not isinstance(row, CorrectionFact) for row in self.records
        ):
            raise ValueError("correction_fact_invalid")

    def rows(self, kind: str):
        return tuple(row.data for row in self.records if row.kind == kind)

    def one(self, kind: str, key=None, value=None):
        rows = self.rows(kind)
        if key is not None:
            rows = tuple(row for row in rows if row.get(key) == str(value))
        if len(rows) != 1:
            raise ValueError("correction_fact_unavailable")
        return rows[0]


@dataclass(frozen=True, slots=True, kw_only=True)
class _CorrectionCommand:
    actor_id: UUID
    operation_key: str
    reason: str

    def __post_init__(self) -> None:
        require_uuid(self.actor_id)
        require_text(self.operation_key, 256)
        require_text(self.reason)


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestSelectionRefund(_CorrectionCommand):
    order_id: UUID
    paid_item_ids: tuple[UUID, ...]
    expected_source_hash: str
    existing_case_id: UUID | None = None

    def __post_init__(self) -> None:
        _CorrectionCommand.__post_init__(self)
        require_uuid(self.order_id)
        if self.existing_case_id is not None:
            require_uuid(self.existing_case_id)
        require_hash(self.expected_source_hash)
        selected = uuid_tuple(self.paid_item_ids)
        if not 1 <= len(selected) <= 200:
            raise ValueError("correction_selection_required")
        object.__setattr__(self, "paid_item_ids", selected)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewSelectionRefund(_CorrectionCommand):
    case_id: UUID
    expected_version: int
    expected_source_hash: str
    decision: Literal["approve", "reject"]
    evidence_reference: str
    evidence_hash: str

    def __post_init__(self) -> None:
        _CorrectionCommand.__post_init__(self)
        require_uuid(self.case_id)
        require_version(self.expected_version)
        require_hash(self.expected_source_hash)
        require_text(self.evidence_reference)
        require_hash(self.evidence_hash)
        if self.decision not in ("approve", "reject"):
            raise ValueError("correction_review_decision_invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordManualRefundObservation(_CorrectionCommand):
    """Retained reported facts, including unsupported or unresolved economics.

    Signed amounts and unknown currency text never authorize positive funding.
    """

    case_id: UUID | None
    known_order_id: UUID | None
    known_capture_intent_id: UUID | None
    original_payment_reference: str
    bank_account_label: str
    bank_reference: str
    amount_minor: int | None
    currency: str | None
    occurred_at: datetime | None
    reported_component: Component
    evidence_reference: str
    evidence_hash: str
    expected_version: int | None
    provenance: Literal["manual_admin_observation"] = field(
        default="manual_admin_observation", init=False
    )

    def __post_init__(self) -> None:
        _CorrectionCommand.__post_init__(self)
        for value in (
            self.case_id,
            self.known_order_id,
            self.known_capture_intent_id,
        ):
            if value is not None:
                require_uuid(value)
        self._validate_provenance()
        self._validate_reported_money()
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", utc(self.occurred_at))
        if self.expected_version is not None:
            require_version(self.expected_version)
        if self.reported_component not in COMPONENTS:
            raise ValueError("correction_component_invalid")

    def _validate_provenance(self) -> None:
        for label in (self.original_payment_reference, self.bank_account_label):
            if not isinstance(label, str) or len(label) > 4000:
                raise ValueError("correction_observation_label_invalid")
        for text in (self.bank_reference, self.evidence_reference):
            require_text(text)
        require_hash(self.evidence_hash)

    def _validate_reported_money(self) -> None:
        if self.amount_minor is not None and (
            type(self.amount_minor) is not int
            or not -(MAX_MINOR + 1) <= self.amount_minor <= MAX_MINOR
        ):
            raise ValueError("correction_observed_minor_invalid")
        if self.currency is not None and (
            not isinstance(self.currency, str) or len(self.currency) > 64
        ):
            raise ValueError("correction_observed_currency_invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class MatchSelectionRefund(_CorrectionCommand):
    case_id: UUID
    intent_id: UUID
    observation_id: UUID
    expected_version: int
    expected_source_hash: str
    evidence_reference: str
    evidence_hash: str

    def __post_init__(self) -> None:
        _CorrectionCommand.__post_init__(self)
        for value in (self.case_id, self.intent_id, self.observation_id):
            require_uuid(value)
        require_version(self.expected_version)
        require_hash(self.expected_source_hash)
        require_text(self.evidence_reference)
        require_hash(self.evidence_hash)


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplySelectionRefund(MatchSelectionRefund):
    match_id: UUID

    def __post_init__(self) -> None:
        MatchSelectionRefund.__post_init__(self)
        require_uuid(self.match_id)


CorrectionCommand = (
    RequestSelectionRefund
    | ReviewSelectionRefund
    | RecordManualRefundObservation
    | MatchSelectionRefund
    | ApplySelectionRefund
)


def correction_command_hash(command: CorrectionCommand) -> str:
    if not isinstance(
        command,
        (
            RequestSelectionRefund,
            ReviewSelectionRefund,
            RecordManualRefundObservation,
            MatchSelectionRefund,
        ),
    ):
        raise ValueError("correction_command_invalid")
    # Include command kind: identical field values must not cross action types.
    return correction_payload_hash((type(command).__name__, command))


def correction_command_id(command: CorrectionCommand) -> UUID:
    """Existing Task2 receipt UUID convention, kept outside economic hashes."""
    return uuid5(
        NAMESPACE_URL,
        f"ugc:correction:{command.actor_id}:{len(command.operation_key)}:{command.operation_key}",
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionScope:
    """Server sources discovered before the COMPLETE sorted User barrier.

    Missing facts stay unavailable. Lock methods never add a late User/wallet.
    """

    actor_id: UUID
    prospective_user_ids: tuple[UUID, ...]
    wallet_user_ids: tuple[UUID, ...]
    source_hash: str | None
    order_id: UUID | None = None
    client_id: UUID | None = None
    intent_id: UUID | None = None
    capture_id: UUID | None = None
    payment_id: UUID | None = None
    captured_at: datetime | None = None
    quote_key: str | None = None
    terms_reference: str | None = None
    bundle: SelectionRefundBundle | None = None
    ground_ids: tuple[UUID, ...] = ()
    unavailable_reason: str | None = None
    case_id: UUID | None = None
    selected_paid_item_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        require_uuid(self.actor_id)
        if self.case_id is not None:
            require_uuid(self.case_id)
        selected = uuid_tuple(self.selected_paid_item_ids)
        if len(selected) > 200:
            raise ValueError("correction_selection_required")
        object.__setattr__(self, "selected_paid_item_ids", selected)
        for name in ("prospective_user_ids", "wallet_user_ids", "ground_ids"):
            object.__setattr__(self, name, uuid_tuple(getattr(self, name)))
        if self.actor_id not in self.prospective_user_ids or not set(
            self.wallet_user_ids
        ).issubset(self.prospective_user_ids):
            raise ValueError("correction_complete_barrier_required")
        self._validate_sources()
        if self.available:
            self._require_complete()

    def _validate_sources(self) -> None:
        for identity in (
            self.order_id,
            self.client_id,
            self.intent_id,
            self.capture_id,
            self.payment_id,
        ):
            if identity is not None:
                require_uuid(identity)
        if self.source_hash is not None:
            require_hash(self.source_hash)
        if self.captured_at is not None:
            object.__setattr__(self, "captured_at", utc(self.captured_at))
        for text in (
            self.quote_key,
            self.terms_reference,
            self.unavailable_reason,
        ):
            if text is not None:
                require_text(text)
        if self.bundle is not None and not isinstance(
            self.bundle, SelectionRefundBundle
        ):
            raise ValueError("correction_full_bundle_required")

    def _require_complete(self) -> None:
        if any(
            value is None
            for value in (
                self.source_hash,
                self.order_id,
                self.client_id,
                self.intent_id,
                self.capture_id,
                self.payment_id,
                self.captured_at,
                self.quote_key,
                self.terms_reference,
                self.bundle,
            )
        ):
            raise ValueError("correction_source_unavailable")
        assert self.bundle is not None
        if (
            self.client_id not in self.prospective_user_ids
            or self.bundle.components[0].payment_id != self.payment_id
        ):
            raise ValueError("correction_source_scope_invalid")

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None


@dataclass(frozen=True, slots=True, kw_only=True)
class OriginalAssessmentLine:
    """Actual post-issue facts, not a caller boolean or a consumer receipt.

    issuance_entry_id is the real appended movement UUID; potential_id is the
    durable covered no-referrer audit identity. Unavailable has neither money
    nor an invented recipient/potential. No zero journal is represented.
    """

    paid_item_id: UUID
    allocation_key: str
    base_minor: int
    currency: str
    business_key: str
    status: Literal["issued", "covered_absence", "unavailable"]
    snapshot_id: UUID | None = None
    potential_id: UUID | None = None
    obligation_id: UUID | None = None
    issuance_entry_id: UUID | None = None
    recipient_id: UUID | None = None
    frozen_rate_bps: int | None = None
    liability_minor: int | None = None
    override_id: UUID | None = None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        require_uuid(self.paid_item_id)
        require_text(self.allocation_key, 256)
        require_text(self.business_key, 256)
        require_minor(self.base_minor, positive=True)
        require_currency(self.currency)
        for value in (
            self.snapshot_id,
            self.potential_id,
            self.obligation_id,
            self.issuance_entry_id,
            self.recipient_id,
            self.override_id,
        ):
            if value is not None:
                require_uuid(value)
        if self.liability_minor is not None:
            require_minor(self.liability_minor)
        self._validate_status()

    def _validate_status(self) -> None:
        if self.status == "issued":
            self._require_issued()
        elif self.status == "covered_absence":
            if self.potential_id is None or self.liability_minor != 0:
                raise ValueError("correction_covered_absence_required")
            self._require_no_obligation()
        elif self.status == "unavailable":
            if (
                self.potential_id is not None
                or self.liability_minor is not None
            ):
                raise ValueError("correction_unavailable_has_no_money")
            if self.unavailable_reason is None:
                raise ValueError("correction_unavailable_reason_required")
            require_text(self.unavailable_reason)
            self._require_no_obligation()
        else:
            raise ValueError("correction_assessment_status_invalid")
        if self.status != "unavailable" and self.unavailable_reason is not None:
            raise ValueError("correction_assessment_reason_invalid")

    def _require_issued(self) -> None:
        if (
            any(
                value is None
                for value in (
                    self.snapshot_id,
                    self.obligation_id,
                    self.issuance_entry_id,
                    self.recipient_id,
                    self.frozen_rate_bps,
                    self.liability_minor,
                )
            )
            or self.potential_id is not None
        ):
            raise ValueError("correction_actual_issuance_required")
        assert self.frozen_rate_bps is not None
        if (
            self.liability_minor
            != commission_minor(
                self.base_minor, self.frozen_rate_bps, self.currency
            )
            or self.liability_minor == 0
        ):
            raise ValueError("correction_original_commission_invalid")

    def _require_no_obligation(self) -> None:
        if any(
            value is not None
            for value in (
                self.snapshot_id,
                self.obligation_id,
                self.issuance_entry_id,
                self.recipient_id,
                self.frozen_rate_bps,
                self.override_id,
            )
        ):
            raise ValueError("correction_no_obligation_required")


@dataclass(frozen=True, slots=True, kw_only=True)
class OriginalGrossAssessment:
    """Exact capture/event/source lines established after issue, before receipt.

    Only the trusted consumer constructs this value in its caller transaction.
    A compensation hook must revalidate actual persisted basis/potential facts.
    """

    capture_id: UUID
    event_id: UUID
    payment_id: UUID
    source_hash: str
    lines: tuple[OriginalAssessmentLine, ...]

    def __post_init__(self) -> None:
        for value in (self.capture_id, self.event_id, self.payment_id):
            require_uuid(value)
        require_hash(self.source_hash)
        if (
            type(self.lines) is not tuple
            or not self.lines
            or any(
                not isinstance(line, OriginalAssessmentLine)
                for line in self.lines
            )
            or len({line.paid_item_id for line in self.lines})
            != len(self.lines)
            or len({line.allocation_key for line in self.lines})
            != len(self.lines)
        ):
            raise ValueError("correction_original_assessment_lines_invalid")
        object.__setattr__(
            self,
            "lines",
            tuple(sorted(self.lines, key=lambda line: line.paid_item_id)),
        )

    @property
    def available(self) -> bool:
        return all(line.status != "unavailable" for line in self.lines)


class CorrectionRepository(Protocol):
    async def management_refund_disposition(
        self, paid_item_id: UUID, *, session: object
    ) -> str | None: ...
    async def prepare_users(
        self, scope: CorrectionScope, *, session: object
    ) -> None:
        """Acquire all sorted prospective Users without wallet/source work."""
        ...

    async def lock_prepared_scope(
        self, scope: CorrectionScope, *, session: object
    ) -> None:
        """Users are already held and current action authority has passed."""
        ...

    async def read_authority(
        self,
        scope: CorrectionScope,
        *,
        operation_key: str | None = None,
        session: object,
    ) -> CorrectionReadAuthority:
        """Load only immutable owner/action after current native validation."""
        ...

    async def actor(
        self, actor_id: UUID, *, session: object
    ) -> CorrectionActor | None: ...

    async def facts(
        self, scope: CorrectionScope, *, session: object
    ) -> CorrectionFacts: ...

    async def discover_case_scope(
        self, actor_id: UUID, case_id: UUID | None, *, session: object
    ) -> CorrectionScope: ...

    async def discover_operation_scope(
        self, actor_id: UUID, operation_key: str, *, session: object
    ) -> CorrectionScope: ...

    async def append_fact(
        self, name: str, values: dict[str, object], *, session: object
    ) -> None: ...

    async def discover_scope(
        self, command: CorrectionCommand, *, session: object
    ) -> CorrectionScope: ...

    async def lock_scope(
        self, scope: CorrectionScope, *, session: object
    ) -> None: ...

    async def load_scope(
        self, scope: CorrectionScope, *, session: object
    ) -> CorrectionScope: ...

    async def state_authority(
        self, case_id: UUID, *, session: object
    ) -> tuple[CorrectionState | None, bool]: ...

    async def command(
        self, actor_id: UUID, operation_key: str, *, session: object
    ) -> dict[str, object] | None: ...

    async def save_command(
        self,
        command: CorrectionCommand,
        payload_hash: str,
        result: dict[str, object],
        *,
        session: object,
    ) -> None: ...

    def application_savepoint(
        self, *, session: object
    ) -> AbstractAsyncContextManager[object]: ...

    async def append_event(
        self, event: CorrectionEvent, *, session: object
    ) -> None: ...

    async def reservation_release_funding(
        self, paid_item_id: UUID, *, session: object
    ) -> tuple[ComponentFunding, ...]: ...

    async def live_funding(
        self, paid_item_id: UUID, *, session: object
    ) -> tuple[ComponentFunding, ...]: ...


class CorrectionFundingGuard(Protocol):
    async def load_item(
        self, paid_item_id: UUID, *, session: object
    ) -> tuple[ComponentFunding, ...]: ...

    async def require_forward_clear(
        self, paid_item_id: UUID, *, session: object
    ) -> None: ...


class ClientRefundCompensation(Protocol):
    async def prepare_original_assessment(
        self, capture: ClientCapture, *, session: object
    ) -> tuple[UUID, ...]: ...

    async def apply_matched_for_capture(
        self,
        capture: ClientCapture,
        *,
        assessment: OriginalGrossAssessment | None = None,
        session: object,
    ) -> tuple[UUID, ...]: ...


class CorrectionApplicationRefused(ValueError):
    """Expected refusal; retain the observation outside the savepoint."""
