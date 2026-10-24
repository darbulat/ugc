"""One requested service, with no invented payment or assignment."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from ugc_bot.domain.enums import OrderType
from ugc_bot.domain.financial import utc


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderIntakeCommand:
    client_id: UUID
    operation_key: str
    policy_version: str
    product_link: str
    offer_text: str
    honorarium: Decimal
    selection_due_at: datetime
    contact_reference: str
    service_mode: Literal["self_service", "with_manager"]
    accompaniment_ordinals: frozenset[int] | None = None
    order_type: OrderType = OrderType.UGC_ONLY
    barter_description: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.client_id, UUID) or self.client_id.int == 0:
            raise ValueError("client_identity_required")
        for name, limit in (
            ("operation_key", 256),
            ("policy_version", 256),
            ("product_link", 2048),
            ("offer_text", 4000),
            ("contact_reference", 500),
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > limit
            ):
                raise ValueError("intake_provenance_required")
            object.__setattr__(self, name, value.strip())
        object.__setattr__(self, "accompaniment_ordinals", self._positions())
        try:
            amount = Decimal(self.honorarium)
            if (
                not amount.is_finite()
                or amount < 0
                or amount.quantize(Decimal("0.01")) != amount
            ):
                raise ValueError("invalid_direct_honorarium")
            object.__setattr__(
                self, "honorarium", amount.quantize(Decimal("0.01"))
            )
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("invalid_direct_honorarium") from exc
        object.__setattr__(self, "selection_due_at", utc(self.selection_due_at))
        object.__setattr__(self, "order_type", OrderType(self.order_type))
        object.__setattr__(
            self,
            "barter_description",
            (self.barter_description or "").strip() or None,
        )

    def _positions(self) -> frozenset[int]:
        if self.service_mode not in ("self_service", "with_manager"):
            raise ValueError("invalid_service_mode")
        selected = self.accompaniment_ordinals
        if self.service_mode == "self_service":
            if selected:
                raise ValueError("self_service_has_no_accompaniment")
            return frozenset()
        if selected is None:
            return frozenset(range(1, 31))
        if not selected or any(
            type(n) is not int or not 1 <= n <= 30 for n in selected
        ):
            raise ValueError("invalid_accompaniment_ordinals")
        return frozenset(selected)

    @property
    def request_id(self) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"ugc:intake:{self.client_id}:{len(self.operation_key)}:{self.operation_key}",
        )

    @property
    def order_id(self) -> UUID:
        return uuid5(self.request_id, "order")

    @property
    def payload_hash(self) -> str:
        payload = dict(
            client_id=str(self.client_id),
            policy_version=self.policy_version,
            product_link=self.product_link,
            offer_text=self.offer_text,
            honorarium=str(self.honorarium),
            order_type=self.order_type.value,
            barter_description=self.barter_description,
            selection_due_at=self.selection_due_at.isoformat(),
            contact_reference=self.contact_reference,
            service_mode=self.service_mode,
            accompaniment_ordinals=sorted(self.accompaniment_ordinals or ()),
        )
        return hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class IntakeItem:
    paid_item_id: UUID
    ordinal: int
    selection_minor: int
    accompaniment_minor: int


@dataclass(frozen=True, slots=True)
class OrderIntakeResult:
    request_id: UUID
    order_id: UUID
    requested_at: datetime
    currency: str
    policy_version: str
    selection_due_at: datetime
    terms_reference: str
    items: tuple[IntakeItem, ...]
    lead_id: UUID | None
    honorarium_payment: Literal["paid_direct"] = "paid_direct"

    @property
    def total_minor(self) -> int:
        return sum(
            i.selection_minor + i.accompaniment_minor for i in self.items
        )

    @property
    def selection_base_minor(self) -> int:
        return sum(i.selection_minor for i in self.items)


@dataclass(frozen=True, slots=True)
class IntakeClient:
    client_id: UUID
    status: str
    is_advertiser: bool
    currency: str
    telegram_id: str | None = None
    max_id: str | None = None


@dataclass(frozen=True, slots=True)
class OrderIntakeReceipt:
    client_id: UUID
    operation_key: str
    payload_hash: str
    result: OrderIntakeResult


@dataclass(frozen=True, slots=True)
class AccompanimentLead:
    lead_id: UUID
    request_id: UUID
    order_id: UUID
    client_id: UUID
    requested_at: datetime
    contact_reference: str
    selected_ordinals: tuple[int, ...]
    state: str = field(default="requested_unpaid", init=False)


@dataclass(frozen=True, slots=True)
class EligibleOrderPolicy:
    version: str
    terms_reference: str
    effective_from: datetime
    refund_window_seconds: int
    currency: str = "RUB"
    position_count: int = 30
    selection_minor: int = 50000
    accompaniment_minor: int = 120000


@dataclass(frozen=True, slots=True)
class EligibleOrderPolicies:
    currency: str
    writes_paused: bool
    policies: tuple[EligibleOrderPolicy, ...]
