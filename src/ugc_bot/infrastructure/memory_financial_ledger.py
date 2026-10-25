"""Transactional memory ledger, including trusted source and approval facts."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

from ugc_bot.application.financial_ports import (
    ActiveEconomicGround,
    ObligationBasis,
    PotentialBasis,
)

BUCKETS = (
    "pending",
    "hold",
    "available",
    "reserved",
    "blocked",
    "paid",
    "cancelled",
    "debt",
)


class InMemoryFinancialLedgerRepository:
    def __init__(self):
        self.records = {}
        self.potentials = {}
        self.movements = {}
        self.entry_ids = {}
        self.wallets = {}
        self.active_grounds = {}
        self.maturities = {}
        self.overrides = {}
        self.maturity_sources = {}
        self.selection_maturity_sources = {}
        self.manual_grant_sources = {}
        self._lock = asyncio.Lock()

    async def load_selection_maturity(self, obligation_id, *, session):
        return self.selection_maturity_sources.get(obligation_id)

    async def load_manual_grant(self, grant_id, *, session):
        self._session(session)
        return self.manual_grant_sources.get(grant_id)

    @asynccontextmanager
    async def transaction(self):
        async with self._lock:
            names = (
                "records",
                "potentials",
                "movements",
                "entry_ids",
                "wallets",
                "active_grounds",
                "maturities",
            )
            before = {name: deepcopy(getattr(self, name)) for name in names}
            session = {"owner": self}
            try:
                yield session
            except BaseException:
                for name, value in before.items():
                    setattr(self, name, value)
                raise
            finally:
                session["owner"] = None

    def _session(self, session):
        if not isinstance(session, dict) or session.get("owner") is not self:
            raise ValueError("caller_transaction_required")

    async def lock_recipients(self, recipient_ids, *, session):
        self._session(session)

    async def lock_wallets(self, keys, *, session):
        self._session(session)
        for recipient, currency in keys:
            if currency != "RUB":
                raise ValueError("unpublished_currency")
            self.wallets.setdefault(
                (recipient, currency), dict.fromkeys(BUCKETS, 0)
            )

    async def lock_item(self, item_id, *, session):
        self._session(session)

    async def get_issue(self, key, *, session):
        self._session(session)
        return self.records.get(key)

    async def save_issue(self, record, *, session):
        self._session(session)
        b = record.basis
        for old in self.records.values():
            o = old.basis
            if (
                o.paid_item_id,
                o.recipient_id,
                o.kind,
                o.assignment_id if o.kind != "client_referral" else None,
            ) == (
                b.paid_item_id,
                b.recipient_id,
                b.kind,
                b.assignment_id if b.kind != "client_referral" else None,
            ):
                raise ValueError("economic_basis_already_exists")
        self.records[b.business_key] = record
        return record

    async def save_potential(self, basis, reason, *, recorded_at, session):
        self._session(session)
        old = self.potentials.get(basis.business_key)
        if old is not None:
            if old.basis != basis or old.reason != reason:
                raise ValueError("idempotency_payload_conflict")
            return old
        value = PotentialBasis(basis, reason, recorded_at, uuid4())
        self.potentials[basis.business_key] = value
        return value

    async def append(self, movement, *, session):
        self._session(session)
        previous = self.movements.get(movement.operation_key)
        if previous is not None:
            if replace(previous, recorded_at=movement.recorded_at) != movement:
                raise ValueError("idempotency_payload_conflict")
            return previous
        if movement.source_entry_id is not None:
            original = next(
                (
                    m
                    for key, m in self.movements.items()
                    if self.entry_ids[key] == movement.source_entry_id
                ),
                None,
            )
            if (
                original is None
                or original.obligation_id != movement.obligation_id
                or original.currency != movement.currency
            ):
                raise ValueError("correction_source_scope_mismatch")
        self.movements[movement.operation_key] = movement
        self.entry_ids[movement.operation_key] = uuid4()
        return movement

    async def get_entry_ref(self, operation_key, *, session):
        self._session(session)
        return self.entry_ids.get(operation_key)

    async def apply_projection(self, movement, *, session):
        self._session(session)
        record = next(
            record
            for record in self.records.values()
            if record.obligation_id == movement.obligation_id
        )
        wallet = self.wallets[(record.basis.recipient_id, movement.currency)]
        if movement.bucket_from:
            wallet[movement.bucket_from] -= movement.amount_minor
        if movement.bucket_to:
            wallet[movement.bucket_to] += movement.amount_minor
        if movement.movement_type == "debt":
            wallet["debt"] += movement.amount_minor
            wallet["cancelled"] += movement.amount_minor
        elif movement.movement_type == "recovery":
            wallet["debt"] -= movement.amount_minor
        if any(value < 0 for value in wallet.values()):
            raise ValueError("negative_wallet_projection")

    async def list_obligation_bases(self, recipient_id, currency, *, session):
        self._session(session)
        return tuple(
            ObligationBasis(
                record.obligation_id,
                recipient_id,
                currency,
                record.movement.amount_minor,
            )
            for record in self.records.values()
            if record.basis.recipient_id == recipient_id
            and record.basis.currency == currency
        )

    async def list_for_recipient(self, recipient_id, currency, *, session):
        self._session(session)
        identities = {
            record.obligation_id
            for record in self.records.values()
            if record.basis.recipient_id == recipient_id
            and record.basis.currency == currency
        }
        return tuple(
            movement
            for movement in self.movements.values()
            if movement.obligation_id in identities
        )

    async def read_projection(self, recipient_id, currency, *, session):
        self._session(session)
        return dict(
            self.wallets.get(
                (recipient_id, currency), dict.fromkeys(BUCKETS, 0)
            )
        )

    async def get_rate_override(self, override_id, *, as_of=None, session):
        self._session(session)
        return self.overrides.get(override_id)

    async def list_item_grounds(self, item_id, kind, *, session):
        self._session(session)
        return tuple(
            ActiveEconomicGround(
                record.obligation_id,
                record.basis.business_key,
                record.basis.recipient_id,
                record.basis.currency,
                item_id,
                kind,
            )
            for record in self.records.values()
            if record.basis.paid_item_id == item_id
            and record.basis.kind == kind
        )

    async def get_active_ground(self, item_id, kind, *, session):
        self._session(session)
        return self.active_grounds.get((item_id, kind))

    async def set_active_ground(self, record, *, session):
        self._session(session)
        b = record.basis
        self.active_grounds[(b.paid_item_id, b.kind)] = ActiveEconomicGround(
            record.obligation_id,
            b.business_key,
            b.recipient_id,
            b.currency,
            b.paid_item_id,
            b.kind,
        )

    async def load_maturity_source(self, source_id, *, session):
        self._session(session)
        return self.maturity_sources.get(source_id)

    async def get_maturity(self, obligation_id, *, session):
        self._session(session)
        return self.maturities.get(obligation_id)

    async def save_maturity(self, fact, *, session):
        self._session(session)
        previous = self.maturities.get(fact.obligation_id)
        if previous is not None:
            if (
                replace(
                    fact,
                    maturity_id=previous.maturity_id,
                    recorded_at=previous.recorded_at,
                )
                != previous
            ):
                raise ValueError("idempotency_payload_conflict")
            return previous
        self.maturities[fact.obligation_id] = fact
        return fact
