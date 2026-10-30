"""Reload captured funding; JSON alone never establishes monetary authority."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import insert, select

from ugc_bot.application.entitlement_ports import ClientCapture, FundedSelection
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyService,
)
from ugc_bot.domain.enums import PaymentStatus
from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.entitlement_models import (
    ClientEntitlementReceiptModel,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import (
    PROVIDER,
    capture_id,
    intent_id,
)
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
    _session,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    _canonical,
    payload_hash,
)
from ugc_bot.infrastructure.db.repositories.financial_policy import (
    SqlAlchemyFinancialPolicyRepository,
)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


async def _row(db, name, key, value):
    table = Base.metadata.tables[name]
    row = (
        (await db.execute(select(table).where(table.c[key] == value)))
        .mappings()
        .one_or_none()
    )
    _require(row is not None, "capture_funding_missing")
    return row


async def _source(db, event):
    source = await _row(db, "outbox_events", "event_id", event.event_id)
    _require(
        source["event_type"]
        == event.event_type
        == "financial.client_snapshot_requested"
        and source["aggregate_type"] == event.aggregate_type == "order"
        and source["aggregate_id"] == event.aggregate_id
        and source["payload"] == event.payload,
        "capture_source_mismatch",
    )
    return source


def _source_hash(source):
    return payload_hash(
        {
            key: source[key]
            for key in (
                "event_id",
                "event_type",
                "aggregate_id",
                "aggregate_type",
                "payload",
            )
        }
    )


class SqlAlchemyClientEntitlementRepository:
    async def source_hash(self, event, *, session):
        return _source_hash(await _source(_session(session), event))

    async def load_capture(self, event, *, session):
        db = _session(session)
        source = await _source(db, event)
        order_id = UUID(source["aggregate_id"])
        order = await _row(db, "orders", "order_id", order_id)
        payment = await _row(db, "payments", "order_id", order_id)
        item_table = Base.metadata.tables["order_items"]
        items = (
            (
                await db.execute(
                    select(item_table)
                    .where(item_table.c.order_id == order_id)
                    .order_by(item_table.c.ordinal)
                )
            )
            .mappings()
            .all()
        )
        _require(bool(items), "capture_items_missing")
        payload = source["payload"]
        identity = payload.get("capture", {})
        _require(isinstance(identity, dict), "capture_source_mismatch")
        self._require_payment(order, payment, identity)
        at = utc(payment["paid_at"])
        intent = await _row(
            db, "outbox_events", "event_id", intent_id(order_id)
        )
        self._require_intent(intent, order, payment, items, identity, at)
        await self._require_allocations(db, order_id, payment, items)
        policy = await SqlAlchemyFinancialPolicyRepository().load(
            order["financial_version"], session=db
        )
        policy, effective = FinancialPolicyService._approved_policy(
            policy, order["financial_version"]
        )
        self._require_policy(policy, effective, order, items, at)
        _require(
            payload.get("payment_id") == str(payment["payment_id"])
            and payload.get("selection_bases")
            == [[str(i["paid_item_id"]), i["selection_minor"]] for i in items]
            and source["event_id"]
            == capture_id(identity["account"], payment["external_id"]),
            "capture_identity_mismatch",
        )
        registered_value = payload.get("client_registered_at")
        registered = (
            utc(datetime.fromisoformat(registered_value))
            if registered_value is not None
            else None
        )
        _require(
            registered is None or registered <= at,
            "capture_registration_after_payment",
        )
        referrer = payload.get("client_referrer_id")
        return ClientCapture(
            source["event_id"],
            order_id,
            payment["payment_id"],
            order["advertiser_id"],
            policy,
            at,
            registered,
            UUID(referrer) if referrer is not None else None,
            tuple(
                FundedSelection(
                    i["paid_item_id"],
                    i["selection_minor"],
                    i["accompaniment_minor"],
                )
                for i in items
            ),
            _source_hash(source),
        )

    @staticmethod
    def _require_payment(order, payment, identity):
        _require(
            order["financial_version"] is not None
            and payment["financial_version"] == order["financial_version"]
            and payment["status"] == PaymentStatus.PAID
            and payment["provider"] == PROVIDER
            and payment["currency"] == "RUB"
            and payment["paid_at"] is not None
            and type(payment["captured_minor"]) is int
            and payment["captured_minor"] > 0
            and payment["amount"] * 100 == payment["captured_minor"]
            and identity.get("captured_at_source") == "telegram.message.date",
            "confirmed_capture_required",
        )

    @staticmethod
    def _require_intent(intent, order, payment, items, identity, at):
        components = [
            [
                str(i["paid_item_id"]),
                i["selection_minor"],
                i["accompaniment_minor"],
            ]
            for i in items
        ]
        expected = {
            "order_id": str(order["order_id"]),
            "client_id": str(order["advertiser_id"]),
            "provider": PROVIDER,
            "account": identity.get("account"),
            "currency": "RUB",
            "amount_minor": sum(i[1] + i[2] for i in components),
            "policy_version": order["financial_version"],
            "quote_key": items[0]["quote_key"],
            "components": components,
        }
        _require(
            intent["event_type"] == "financial.capture_intent"
            and intent["aggregate_id"] == str(order["order_id"])
            and intent["aggregate_type"] == "order"
            and intent["payload"] == expected
            and isinstance(expected["account"], str)
            and bool(expected["account"].strip())
            and type(identity.get("amount_minor")) is int
            and expected["amount_minor"] == payment["captured_minor"],
            "capture_intent_mismatch",
        )
        _require(
            identity
            == dict(
                expected,
                external_id=payment["external_id"],
                telegram_payment_charge_id=identity.get(
                    "telegram_payment_charge_id"
                ),
                captured_at=identity.get("captured_at"),
                captured_at_source="telegram.message.date",
            )
            and isinstance(identity.get("telegram_payment_charge_id"), str)
            and bool(identity["telegram_payment_charge_id"].strip())
            and utc(datetime.fromisoformat(identity["captured_at"])) == at
            and at <= datetime.now(timezone.utc),
            "capture_identity_mismatch",
        )

    @staticmethod
    async def _require_allocations(db, order_id, payment, items):
        table = Base.metadata.tables["payment_item_allocations"]
        rows = (
            (
                await db.execute(
                    select(table).where(table.c.order_id == order_id)
                )
            )
            .mappings()
            .all()
        )
        actual = {
            (
                row["paid_item_id"],
                row["component"],
                row["amount_minor"],
                row["payment_id"],
                row["currency"],
            )
            for row in rows
        }
        expected = {
            (
                i["paid_item_id"],
                component,
                i[field],
                payment["payment_id"],
                "RUB",
            )
            for i in items
            for component, field in (
                ("selection", "selection_minor"),
                ("accompaniment", "accompaniment_minor"),
            )
            if i[field]
        }
        _require(actual == expected, "capture_allocation_mismatch")

    @staticmethod
    def _require_policy(policy, effective, order, items, at):
        _require(
            effective <= utc(order["created_at"]) <= at
            and order["advertiser_id"] in policy.allowed_clients
            and bool(policy.terms_reference)
            and policy.selection_refund_window is not None
            and policy.selection_refund_window > timedelta(0),
            "capture_policy_mismatch",
        )
        for item in items:
            quote = item["quote_payload"]
            _require(
                item["currency"] == "RUB"
                and item["policy_version"] == policy.version
                and item["quote_key"] == items[0]["quote_key"]
                and item["selection_minor"] == policy.selection_minor
                and item["accompaniment_minor"]
                in (0, policy.accompaniment_minor)
                and item["captured_at"] == at
                and item["selection_state"] not in ("refunded", "cancelled")
                and utc(item["selection_due_at"]) > at
                and quote.get("client_id") == str(order["advertiser_id"])
                and quote.get("terms_reference") == policy.terms_reference,
                "capture_item_mismatch",
            )

    async def lock_funding(self, capture, *, session):
        db = _session(session)
        await SqlAlchemyFinancialItemRepository().lock_order(
            capture.order_id, session=db
        )
        for name, column, value in (
            ("orders", "order_id", capture.order_id),
            ("payments", "payment_id", capture.payment_id),
        ):
            table = Base.metadata.tables[name]
            await db.execute(
                select(table.c[column])
                .where(table.c[column] == value)
                .with_for_update()
            )

    async def get_receipt(self, event_id, *, session):
        table = ClientEntitlementReceiptModel.__table__
        return (
            (
                await _session(session).execute(
                    select(table).where(table.c.event_id == event_id)
                )
            )
            .mappings()
            .one_or_none()
        )

    async def save_receipt(
        self,
        capture,
        assessment,
        *,
        recorded_at,
        session,
    ):
        await _session(session).execute(
            insert(ClientEntitlementReceiptModel.__table__).values(
                event_id=capture.event_id,
                order_id=capture.order_id,
                payment_id=capture.payment_id,
                source_hash=capture.source_hash,
                assessment=_canonical(assessment),
                recorded_at=recorded_at,
            )
        )
