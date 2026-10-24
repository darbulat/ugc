"""Immutable payout read facts and untrusted navigation cursors."""

import base64
import json
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from ugc_bot.application.financial_ports import JournalMovement, ObligationBasis
from ugc_bot.domain.financial import utc

Platform = Literal["telegram", "max"]


class PayoutReadNotFound(LookupError):
    """Known scoped absence, distinct from broken data or network failure."""


@dataclass(frozen=True, slots=True)
class PayoutReadPrincipal:
    actor_id: UUID
    platform: Platform
    external_id: str

    def __post_init__(self):
        if (
            not isinstance(self.actor_id, UUID)
            or not self.actor_id.int
            or self.platform not in ("telegram", "max")
            or not isinstance(self.external_id, str)
            or not self.external_id
            or len(self.external_id) > 128
        ):
            raise ValueError("payout_read_identity_invalid")


@dataclass(frozen=True, slots=True)
class ReadActor:
    actor_id: UUID
    platform: str
    external_id: str
    status: str
    admin: bool


@dataclass(frozen=True, slots=True)
class ReadObligation:
    basis: ObligationBasis
    paid_item_id: UUID


@dataclass(frozen=True, slots=True)
class FinancialRead:
    obligations: tuple[ReadObligation, ...]
    movements: tuple[JournalMovement, ...]
    wallet: Mapping[str, int] | None
    source_blockers: tuple[str, ...]
    readiness_blockers: tuple[str, ...]
    recipient_status: str | None


@dataclass(frozen=True, slots=True)
class RequirementsRead:
    current: Mapping[str, Any] | None
    latest: Mapping[str, Any] | None
    source_blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RequisiteRead:
    row: Mapping[str, Any]
    contract: Mapping[str, Any] | None
    accepted: bool
    source_blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadAllocation:
    obligation_id: UUID
    paid_item_id: UUID
    amount_minor: int


@dataclass(frozen=True, slots=True)
class RequestRead:
    row: Mapping[str, Any]
    authority: Mapping[str, Any] | None
    consistent: bool
    requisites: RequisiteRead | None
    allocations: tuple[ReadAllocation, ...]
    current_intent: Mapping[str, Any] | None = None
    retained_intents: tuple[Mapping[str, Any], ...] = ()
    more_intents: bool = False
    escalated: bool = False
    source_blockers: tuple[str, ...] = ()
    observation_ready: bool = False
    observation_blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Page:
    limit: int = 20
    cursor: str | None = None

    def __post_init__(self):
        if (
            type(self.limit) is not int
            or not 1 <= self.limit <= 100
            or (
                self.cursor is not None
                and (
                    not isinstance(self.cursor, str)
                    or not self.cursor
                    or len(self.cursor) > 2048
                )
            )
        ):
            raise ValueError("payout_cursor_invalid")


@dataclass(frozen=True, slots=True)
class Cursor:
    position: datetime | int
    identity: UUID


def _cursor_object(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("payout_cursor_invalid")
        data[key] = value
    return data


def cursor_decode(value, principal, route, scope=None):
    if value is None:
        return None
    try:
        data = json.loads(
            base64.b64decode(
                value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
            ),
            object_pairs_hook=_cursor_object,
        )
        if (
            not isinstance(data, dict)
            or set(data) != {"v", "actor", "route", "scope", "position"}
            or type(data["v"]) is not int
            or data["v"] != 1
            or data["actor"] != str(principal.actor_id)
            or data["route"] != route
            or data["scope"] != (str(scope) if scope else None)
            or not isinstance(data["position"], list)
            or len(data["position"]) != 2
        ):
            raise ValueError()
        position, identity = data["position"]
        identity = UUID(identity)
        if not identity.int:
            raise ValueError()
        if route == "history:events":
            if type(position) is not int or position < 1:
                raise ValueError()
        else:
            position = utc(datetime.fromisoformat(position))
        return Cursor(position, identity)
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        OverflowError,
    ):
        raise ValueError("payout_cursor_invalid") from None


def cursor_encode(cursor, principal, route, scope=None):
    position = (
        cursor.position.isoformat()
        if isinstance(cursor.position, datetime)
        else cursor.position
    )
    data = dict(
        v=1,
        actor=str(principal.actor_id),
        route=route,
        scope=str(scope) if scope else None,
        position=[position, str(cursor.identity)],
    )
    return (
        base64.urlsafe_b64encode(
            json.dumps(data, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )


class PayoutReadSnapshot(Protocol):
    async def actor(
        self, principal: PayoutReadPrincipal
    ) -> ReadActor | None: ...
    async def financial(self, recipient_id: UUID) -> FinancialRead: ...
    async def command_blockers(
        self, kind: Literal["store", "publish", "review"]
    ) -> tuple[str, ...]: ...
    async def requirements(self, at: datetime) -> RequirementsRead: ...
    async def requisites(
        self, recipient_id: UUID, page: Page, cursor: Cursor | None
    ) -> tuple[RequisiteRead, ...]: ...
    async def requisite(
        self, recipient_id: UUID, requisites_id: UUID
    ) -> RequisiteRead | None: ...
    async def item_blockers(
        self, item_ids: tuple[UUID, ...]
    ) -> tuple[str, ...]: ...
    async def request(
        self, request_id: UUID, recipient_id: UUID | None
    ) -> RequestRead | None: ...
    async def requests(
        self,
        recipient_id: UUID | None,
        page: Page,
        cursor: Cursor | None,
        *,
        queue: bool,
    ) -> tuple[RequestRead, ...]: ...
    async def history(
        self, request_id: UUID, kind: str, page: Page, cursor: Cursor | None
    ) -> tuple[Mapping[str, Any], ...]: ...
    async def requirements_page(
        self, page: Page, cursor: Cursor | None
    ) -> tuple[Mapping[str, Any], ...]: ...


class PayoutViewRepository(Protocol):
    def snapshot(self) -> AbstractAsyncContextManager[PayoutReadSnapshot]: ...
