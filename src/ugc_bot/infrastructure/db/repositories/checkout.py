"""Caller-transaction checkout; no remote calls or fabricated paid proof."""

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import insert, select, text, update

from ugc_bot.domain.checkout import CheckoutActor, PreparedInvoice
from ugc_bot.domain.enums import OrderStatus, PaymentStatus, UserStatus
from ugc_bot.infrastructure.db.checkout_models import (
    ATTEMPTS,
    AUTHORIZATIONS,
    CHECKOUTS,
    INBOX,
    INBOX_STATE,
    NOTICE_ATTEMPTS,
    NOTICE_JOBS,
    NOTICE_RESULTS,
    REQUESTS,
    RESULTS,
    REVIEWS,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    CountryModel,
    OrderModel,
    OutboxEventModel,
    PaymentItemAllocationModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import (
    capture_id,
    intent_id,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def now():
    return datetime.now(timezone.utc)


class SqlCheckoutRepository:
    tables = {"requests": REQUESTS, "checkouts": CHECKOUTS, "inbox": INBOX}

    def __init__(self, config, capture):
        self.config, self.capture = config, capture
        self.account = config.bot.telegram_payment_account_id

    async def _owner(self, order_id, actor, db, *, lock=False, active=False):
        query = select(UserModel).where(UserModel.user_id == actor.user_id)
        if lock:
            query = query.with_for_update(key_share=True)
        user = await db.scalar(query.execution_options(populate_existing=True))
        external = getattr(
            user,
            "telegram_id" if actor.platform == "telegram" else "max_id",
            None,
        )
        if user is None or external != actor.external_id:
            raise PermissionError("checkout_identity_changed")
        order = await db.get(OrderModel, order_id)
        if order is None:
            raise LookupError("order_not_found")
        if order.advertiser_id != actor.user_id:
            raise PermissionError("order_not_yours")
        if order.financial_version is None:
            raise ValueError("financial_order_required")
        if active:
            await self._active_advertiser(user, actor, db)
        if lock:
            await self.capture.lock_order(order_id, session=db)
            order = await db.scalar(
                select(OrderModel)
                .where(OrderModel.order_id == order_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if order is None or order.advertiser_id != actor.user_id:
                raise PermissionError("order_not_yours")
        return user, order

    async def _active_advertiser(self, user, actor, db):
        profile = await db.scalar(
            select(AdvertiserProfileModel.user_id)
            .where(AdvertiserProfileModel.user_id == actor.user_id)
            .with_for_update(read=True)
        )
        if user.status != UserStatus.ACTIVE or profile is None:
            raise PermissionError("active_advertiser_required")
        currency = (
            await db.scalar(
                select(CountryModel.currency_code).where(
                    CountryModel.code == user.country
                )
            )
            if user.country
            else None
        )
        if currency != "RUB":
            raise ValueError("unpublished_currency")

    async def _row(self, table, condition, db, *, lock=False):
        query = select(table).where(condition).limit(1)
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).mappings().one_or_none()

    async def _checkout(self, order_id, db, *, lock=False):
        return await self._row(
            CHECKOUTS, CHECKOUTS.c.order_id == order_id, db, lock=lock
        )

    async def prepare(
        self, order_id, actor, operation_key, *, allow_new, retry_of, session
    ):
        db = _session(session)
        if len(operation_key) > 256:
            raise ValueError("invalid_operation_key")
        _, order = await self._owner(order_id, actor, db, lock=True)
        current = await self._checkout(order_id, db, lock=True)
        intent = await db.get(OutboxEventModel, intent_id(order_id))
        if not self._original_client(order, current, intent):
            return await self._snapshot(order, db)
        payload_hash = digest(
            [
                str(order_id),
                actor.external_id,
                str(retry_of) if retry_of else None,
            ]
        )
        request = await self._row(
            REQUESTS,
            (REQUESTS.c.client_id == actor.user_id)
            & (REQUESTS.c.operation_key == operation_key),
            db,
        )
        if request:
            if request.payload_hash != payload_hash:
                raise ValueError("idempotency_payload_conflict")
            return await self._snapshot(order, db)
        if current and (
            current.state == "ready"
            or (current.state == "creating" and current.lease_until > now())
        ):
            await self._request(
                order_id,
                actor,
                operation_key,
                payload_hash,
                current.attempt_id,
                db,
            )
            return await self._snapshot(order, db)
        if not allow_new:
            raise ValueError("financial_disabled")
        if (
            not self.account.strip()
            or not self.config.bot.telegram_provider_token.strip()
            or self.capture is None
        ):
            raise ValueError("payment_provider_not_configured")
        await self._owner(order_id, actor, db, active=True)
        if await self._replay_or_validate_retry(
            order_id, actor, operation_key, payload_hash, current, retry_of, db
        ):
            return await self._snapshot(order, db)
        existing_intent = await db.get(OutboxEventModel, intent_id(order_id))
        if current is None and existing_intent is not None:
            return await self._snapshot(order, db)
        return await self._new_attempt(
            order_id, actor, operation_key, payload_hash, current, order, db
        )

    async def _replay_or_validate_retry(
        self, order_id, actor, key, hashed, current, retry_of, db
    ):
        if current is None:
            if retry_of is not None:
                raise ValueError("checkout_attempt_changed")
            return False
        if retry_of is None:
            await self._request(
                order_id, actor, key, hashed, current.attempt_id, db
            )
            return True
        if retry_of != current.attempt_id or current.account != self.account:
            raise ValueError("checkout_attempt_changed")
        if current.authorization_id is not None:
            raise ValueError("payment_authorization_pending")
        return False

    async def _new_attempt(
        self, order_id, actor, operation_key, payload_hash, current, order, db
    ):
        if order.status != OrderStatus.NEW:
            raise ValueError("uncaptured_new_order_required")
        await self.capture.issue(
            order_id, actor.user_id, self.account, session=db
        )
        _, order, items = await self.capture._locked(
            order_id, actor.user_id, db
        )
        await self.capture._policy(db, order, items, now(), issuing=False)
        intent = await db.get(OutboxEventModel, intent_id(order_id))
        if intent is None:
            raise ValueError("capture_intent_required")
        value = intent.payload
        if value.get("account") != self.account or value.get(
            "client_id"
        ) != str(actor.user_id):
            raise ValueError("capture_intent_mismatch")
        selection = sum(component[1] for component in value["components"])
        accompaniment = sum(component[2] for component in value["components"])
        if (
            type(selection) is not int
            or selection <= 0
            or selection + accompaniment > 100_000_000
        ):
            raise ValueError("invalid_invoice_amount")
        attempt_id = uuid4()
        description = order.offer_text[:255]
        if current:
            original = await self._row(
                ATTEMPTS, ATTEMPTS.c.attempt_id == current.attempt_id, db
            )
            description = original.prepared["description"]
        prepared = PreparedInvoice(
            attempt_id, order_id, "RUB", selection, accompaniment, description
        )
        if current is None:
            await db.execute(
                insert(CHECKOUTS).values(
                    order_id=order_id,
                    client_id=actor.user_id,
                    account=self.account,
                    state="creating",
                    attempt_id=attempt_id,
                    lease_until=now() + timedelta(minutes=2),
                    version=1,
                )
            )
        else:
            await db.execute(
                update(CHECKOUTS)
                .where(CHECKOUTS.c.order_id == order_id)
                .values(
                    state="creating",
                    attempt_id=attempt_id,
                    invoice_url=None,
                    lease_until=now() + timedelta(minutes=2),
                    version=current.version + 1,
                )
            )
        await db.execute(
            insert(ATTEMPTS).values(
                attempt_id=attempt_id,
                order_id=order_id,
                created_at=now(),
                prepared=json.loads(json.dumps(asdict(prepared), default=str)),
            )
        )
        await self._request(
            order_id, actor, operation_key, payload_hash, attempt_id, db
        )
        return prepared

    async def _request(self, order_id, actor, key, hashed, attempt, db):
        await db.execute(
            insert(REQUESTS).values(
                request_id=uuid4(),
                client_id=actor.user_id,
                operation_key=key,
                order_id=order_id,
                payload_hash=hashed,
                attempt_id=attempt,
                created_at=now(),
            )
        )

    async def complete(self, attempt, *, outcome, url, session):
        db = _session(session)
        current = await self._checkout(attempt.order_id, db, lock=True)
        result_id = uuid5(
            NAMESPACE_URL,
            f"checkout-result:{attempt.attempt_id}:{outcome}:{url}",
        )
        if (
            await self._row(RESULTS, RESULTS.c.result_id == result_id, db)
            is None
        ):
            await db.execute(
                insert(RESULTS).values(
                    result_id=result_id,
                    attempt_id=attempt.attempt_id,
                    observed_at=now(),
                    outcome=outcome,
                    invoice_url=url,
                )
            )
        if current.attempt_id == attempt.attempt_id:
            await db.execute(
                update(CHECKOUTS)
                .where(CHECKOUTS.c.order_id == attempt.order_id)
                .values(
                    state=outcome,
                    invoice_url=url,
                    lease_until=None,
                    version=current.version + 1,
                )
            )
        order = await db.get(OrderModel, attempt.order_id)
        return await self._snapshot(order, db)

    async def status(self, order_id, actor, *, session):
        db = _session(session)
        _, order = await self._owner(order_id, actor, db)
        value = await self._snapshot(order, db)
        if actor.platform == "max":
            user = await db.get(UserModel, actor.user_id)
            value["invoice_url"] = None
            value["can_open"] = False
            name = self.config.bot.bot_username
            value["telegram_handoff"] = (
                f"https://t.me/{name}?start=pay_{order_id}"
                if user.telegram_id and name and name.replace("_", "").isalnum()
                else None
            )
            value["reason"] = (
                "telegram_handoff_required"
                if value["telegram_handoff"]
                else "telegram_link_required"
            )
        return value

    @staticmethod
    def _original_client(order, current, intent):
        return (
            current is None or current.client_id == order.advertiser_id
        ) and (
            intent is None
            or intent.payload.get("client_id") == str(order.advertiser_id)
        )

    async def _snapshot(self, order, db):
        current = await self._checkout(order.order_id, db)
        intent = await db.get(OutboxEventModel, intent_id(order.order_id))
        state = (
            current.state
            if current
            else "untracked"
            if intent
            else "not_requested"
        )
        if current and state == "creating" and current.lease_until <= now():
            state = "unknown"
        original_client = self._original_client(order, current, intent)
        if original_client:
            capture_state, captured_at = await self._capture_proof(
                order, intent, db
            )
        else:
            # Retain the paid/link facts for their original client, but expose
            # no attempt, authorization, amount or receipt after reassignment.
            current, intent, state = None, None, "untracked"
            capture_state, captured_at = "unavailable", None
        paused = not (
            self.config.financial.core_enabled
            and self.config.financial.new_orders_enabled
        )
        return dict(
            order_id=order.order_id,
            policy_version=order.financial_version,
            currency="RUB",
            amount_minor=intent.payload["amount_minor"] if intent else None,
            invoice_state=state,
            attempt_id=current.attempt_id if current else None,
            invoice_url=current.invoice_url
            if current and state == "ready"
            else None,
            capture_state=capture_state,
            captured_at=captured_at,
            writes_paused=paused,
            can_open=state == "ready"
            and capture_state == "not_recorded"
            and not paused,
            reason=None if original_client else "checkout_unavailable",
            version=current.version if current else 0,
            authorization_id=current.authorization_id if current else None,
        )

    async def _capture_proof(self, order, intent, db):
        payment = await db.scalar(
            select(PaymentModel).where(PaymentModel.order_id == order.order_id)
        )
        if payment is None or payment.captured_minor is None:
            return (
                ("unavailable", None)
                if payment and payment.status == PaymentStatus.PAID
                else ("not_recorded", None)
            )
        if intent is None:
            return "unavailable", None
        event = await db.get(
            OutboxEventModel,
            capture_id(intent.payload.get("account", ""), payment.external_id),
        )
        capture = event.payload.get("capture", {}) if event else {}
        if (
            event is None
            or event.event_type != "financial.client_snapshot_requested"
            or event.aggregate_id != str(order.order_id)
            or event.payload.get("payment_id") != str(payment.payment_id)
            or any(
                capture.get(key) != value
                for key, value in intent.payload.items()
            )
            or capture.get("external_id") != payment.external_id
            or not capture.get("telegram_payment_charge_id")
            or payment.captured_minor != intent.payload.get("amount_minor")
            or payment.currency != capture.get("currency")
        ):
            return "unavailable", None
        try:
            at = datetime.fromisoformat(capture["captured_at"])
        except (KeyError, TypeError, ValueError):
            return "unavailable", None
        allocations = (
            await db.scalars(
                select(PaymentItemAllocationModel.amount_minor).where(
                    PaymentItemAllocationModel.payment_id == payment.payment_id
                )
            )
        ).all()
        if at != payment.paid_at or sum(allocations) != payment.captured_minor:
            return "unavailable", None
        return "confirmed", at

    async def authorize(
        self,
        order_id,
        external_id,
        query_id,
        amount,
        currency,
        *,
        session,
        allow_new=True,
    ):
        db = _session(session)
        # The native protocol has a short approval deadline; never wait on a
        # sales/admin transaction until Telegram has already timed out.
        await db.execute(text("SET LOCAL lock_timeout = '2s'"))
        await db.execute(text("SET LOCAL statement_timeout = '5s'"))
        order = await db.get(OrderModel, order_id)
        if order is None:
            raise LookupError("order_not_found")
        actor = CheckoutActor(order.advertiser_id, "telegram", external_id)
        _, order = await self._owner(
            order_id, actor, db, lock=True, active=True
        )
        current = await self._checkout(order_id, db, lock=True)
        if (
            current is None
            or current.account != self.account
            or current.client_id != actor.user_id
            or not query_id.strip()
        ):
            raise ValueError("tracked_checkout_required")
        prior = await self._row(
            AUTHORIZATIONS,
            (AUTHORIZATIONS.c.account == self.account)
            & (AUTHORIZATIONS.c.query_id == query_id),
            db,
        )
        intent = await db.get(OutboxEventModel, intent_id(order_id))
        if (
            intent is None
            or type(amount) is not int
            or amount != intent.payload.get("amount_minor")
            or currency != intent.payload.get("currency")
        ):
            raise ValueError("checkout_amount_mismatch")
        if prior:
            if (
                prior.order_id != order_id
                or prior.payer_external_id != external_id
                or prior.amount_minor != amount
                or prior.currency != currency
                or current.authorization_id != prior.authorization_id
            ):
                raise ValueError("native_query_conflict")
            return dict(prior)
        if not (
            allow_new
            and self.config.financial.core_enabled
            and self.config.financial.new_orders_enabled
        ):
            raise ValueError("financial_disabled")
        if current.authorization_id is not None:
            raise ValueError("payment_authorization_pending")
        # Existing intent replay checks its full original owner, quote and
        # provider identity; policy validation uses approval time only here.
        await self.capture.issue(
            order_id, actor.user_id, self.account, session=db
        )
        _, order, items = await self.capture._locked(
            order_id, actor.user_id, db
        )
        await self.capture._policy(db, order, items, now(), issuing=False)
        proof, _ = await self._capture_proof(order, intent, db)
        payment = await db.scalar(
            select(PaymentModel)
            .where(PaymentModel.order_id == order_id)
            .with_for_update()
        )
        if (
            proof != "not_recorded"
            or payment is None
            or payment.status != PaymentStatus.PENDING
            or order.status != OrderStatus.NEW
        ):
            raise ValueError("order_not_payable")
        if await self._row(INBOX, INBOX.c.order_id == order_id, db):
            raise ValueError("paid_receipt_pending")
        value = dict(
            authorization_id=uuid4(),
            order_id=order_id,
            account=self.account,
            query_id=query_id,
            payer_external_id=external_id,
            client_id=actor.user_id,
            amount_minor=amount,
            currency=currency,
            intent_id=intent_id(order_id),
            approved_at=now(),
        )
        await db.execute(insert(AUTHORIZATIONS).values(**value))
        await db.execute(
            update(CHECKOUTS)
            .where(CHECKOUTS.c.order_id == order_id)
            .values(
                authorization_id=value["authorization_id"],
                version=current.version + 1,
            )
        )
        return value

    async def accept_receipt(self, receipt, *, session):
        db = _session(session)
        if (
            not receipt.provider_charge_id
            or not receipt.telegram_charge_id
            or not receipt.payer_external_id
            or not receipt.chat_id
            or not receipt.message_id
            or type(receipt.amount_minor) is not int
            or receipt.amount_minor <= 0
            or receipt.protocol_message_at.tzinfo is None
        ):
            raise ValueError("trusted_native_receipt_required")
        order = await db.get(OrderModel, receipt.order_id)
        if order is not None and order.financial_version is None:
            return False
        if order is not None:
            await db.scalar(
                select(UserModel.user_id)
                .where(UserModel.user_id == order.advertiser_id)
                .with_for_update(key_share=True)
            )
        await self.capture.lock_order(receipt.order_id, session=db)
        await db.scalar(
            select(OrderModel.order_id)
            .where(OrderModel.order_id == receipt.order_id)
            .with_for_update()
        )
        source = (
            f"telegram:{len(receipt.chat_id)}:{receipt.chat_id}:"
            f"{receipt.message_id}"
        )
        receipt_id = uuid5(
            NAMESPACE_URL,
            f"checkout-paid:{len(self.account)}:{self.account}:{source}",
        )
        payload = json.loads(json.dumps(asdict(receipt), default=str))
        hashed = digest(payload)
        existing = await self._row(INBOX, INBOX.c.receipt_id == receipt_id, db)
        if existing:
            if existing.payload_hash != hashed:
                raise ValueError("idempotency_payload_conflict")
            return True
        await db.execute(
            insert(INBOX).values(
                receipt_id=receipt_id,
                order_id=receipt.order_id,
                account=self.account,
                source_key=source,
                payload_hash=hashed,
                receipt=payload,
                received_at=now(),
            )
        )
        await db.execute(
            insert(INBOX_STATE).values(
                receipt_id=receipt_id, state="pending", attempts=0
            )
        )
        return True

    async def review_authorization(
        self,
        authorization_id,
        actor,
        operation_key,
        expected_version,
        reason,
        evidence_reference,
        *,
        session,
    ):
        db = _session(session)
        if (
            actor.platform != "telegram"
            or len(reason.strip()) < 16
            or len(evidence_reference.strip()) < 8
            or not operation_key.strip()
            or len(operation_key) > 256
        ):
            raise ValueError("reasoned_manual_review_required")
        auth = await self._row(
            AUTHORIZATIONS,
            AUTHORIZATIONS.c.authorization_id == authorization_id,
            db,
        )
        if auth is None:
            raise LookupError("authorization_not_found")
        users = (
            await db.scalars(
                select(UserModel)
                .where(UserModel.user_id.in_({actor.user_id, auth.client_id}))
                .order_by(UserModel.user_id)
                .with_for_update(key_share=True)
                .execution_options(populate_existing=True)
            )
        ).all()
        admin = next(
            (user for user in users if user.user_id == actor.user_id), None
        )
        if (
            admin is None
            or admin.admin is not True
            or admin.status != UserStatus.ACTIVE
            or admin.telegram_id != actor.external_id
        ):
            raise PermissionError("current_admin_required")
        await self.capture.lock_order(auth.order_id, session=db)
        order = await db.scalar(
            select(OrderModel)
            .where(OrderModel.order_id == auth.order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if order is None or order.advertiser_id != auth.client_id:
            raise ValueError("authorization_owner_changed")
        current = await self._checkout(auth.order_id, db, lock=True)
        hashed = digest(
            [
                str(authorization_id),
                expected_version,
                reason,
                evidence_reference,
                "confirmed_not_charged",
            ]
        )
        prior = await self._row(
            REVIEWS,
            (REVIEWS.c.actor_id == actor.user_id)
            & (REVIEWS.c.operation_key == operation_key),
            db,
        )
        if prior:
            if prior.payload_hash != hashed:
                raise ValueError("idempotency_payload_conflict")
            return dict(prior)
        if (
            current.authorization_id != authorization_id
            or current.version != expected_version
        ):
            raise ValueError("authorization_version_conflict")
        if await self._row(INBOX, INBOX.c.order_id == auth.order_id, db):
            raise ValueError("paid_receipt_pending")
        intent = await db.get(OutboxEventModel, intent_id(auth.order_id))
        proof, _ = await self._capture_proof(order, intent, db)
        if proof != "not_recorded":
            raise ValueError("captured_or_unavailable_payment")
        value = dict(
            review_id=uuid4(),
            authorization_id=authorization_id,
            actor_id=actor.user_id,
            operation_key=operation_key,
            expected_version=expected_version,
            payload_hash=hashed,
            reason=reason,
            evidence_reference=evidence_reference,
            source="manual_admin_review",
            reviewed_at=now(),
        )
        await db.execute(insert(REVIEWS).values(**value))
        await db.execute(
            update(CHECKOUTS)
            .where(CHECKOUTS.c.order_id == auth.order_id)
            .values(authorization_id=None, version=current.version + 1)
        )
        return value

    async def claim_receipt(self, *, session):
        from ugc_bot.domain.checkout import NativePaidReceipt

        db = _session(session)
        current = (
            (
                await db.execute(
                    select(INBOX_STATE)
                    .where(
                        (INBOX_STATE.c.state == "pending")
                        | (
                            (INBOX_STATE.c.state == "processing")
                            & (INBOX_STATE.c.lease_until <= now())
                        )
                    )
                    .where(
                        INBOX_STATE.c.receipt_id.in_(
                            select(INBOX.c.receipt_id).where(
                                INBOX.c.account == self.account
                            )
                        )
                    )
                    .order_by(INBOX_STATE.c.receipt_id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        if current is None:
            return None
        source = await self._row(
            INBOX, INBOX.c.receipt_id == current.receipt_id, db
        )
        payload = dict(source.receipt)
        payload["order_id"] = UUID(payload["order_id"])
        payload["protocol_message_at"] = datetime.fromisoformat(
            payload["protocol_message_at"]
        )
        receipt = NativePaidReceipt(**payload)
        client = await db.scalar(
            select(UserModel.user_id).where(
                UserModel.telegram_id == receipt.payer_external_id
            )
        )
        if source.account != self.account or not self.account.strip():
            client = None
        claim_id = uuid4()
        lease = now() + timedelta(minutes=2)
        await db.execute(
            update(INBOX_STATE)
            .where(INBOX_STATE.c.receipt_id == current.receipt_id)
            .values(
                state="processing",
                lease_until=lease,
                attempts=current.attempts + 1,
                claim_id=claim_id,
            )
        )
        return dict(
            receipt_id=current.receipt_id,
            claim_id=claim_id,
            lease_until=lease,
            receipt=receipt,
            client_id=client,
        )

    async def finish_receipt(self, claim, state, *, error, session):
        db = _session(session)
        result = await db.execute(
            update(INBOX_STATE)
            .where(
                INBOX_STATE.c.receipt_id == claim["receipt_id"],
                INBOX_STATE.c.claim_id == claim["claim_id"],
                INBOX_STATE.c.state == "processing",
                INBOX_STATE.c.lease_until == claim["lease_until"],
            )
            .values(state=state, error=error, lease_until=None)
        )

        if result.rowcount and state == "captured":
            await self._queue_paid_notices(claim["receipt_id"], db)

    async def _queue_paid_notices(self, receipt_id, db):
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        source = await self._row(INBOX, INBOX.c.receipt_id == receipt_id, db)
        order = await db.get(OrderModel, source.order_id)
        intent = await db.get(OutboxEventModel, intent_id(source.order_id))
        if (
            order is None
            or (await self._capture_proof(order, intent, db))[0] != "confirmed"
        ):
            return
        recipients = (
            await db.scalars(
                select(UserModel).where(
                    (
                        (
                            UserModel.admin.is_(True)
                            & (UserModel.status == UserStatus.ACTIVE)
                        )
                        | (UserModel.user_id == order.advertiser_id)
                    ),
                    UserModel.telegram_id.is_not(None),
                )
            )
        ).all()
        for user in recipients:
            await db.execute(
                pg_insert(NOTICE_JOBS)
                .values(
                    job_id=uuid5(
                        NAMESPACE_URL,
                        f"paid-notice:{order.order_id}:{user.user_id}",
                    ),
                    receipt_id=receipt_id,
                    order_id=order.order_id,
                    recipient_id=user.user_id,
                    account=source.account,
                    kind="client"
                    if user.user_id == order.advertiser_id
                    else "admin",
                    state="ready",
                    attempts=0,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        NOTICE_JOBS.c.order_id,
                        NOTICE_JOBS.c.recipient_id,
                    ]
                )
            )

    async def claim_notice(self, *, session):
        from ugc_bot.application.services.checkout_paid_notices import (
            PaidNotice,
        )

        db = _session(session)
        expired = (
            (
                await db.execute(
                    select(NOTICE_JOBS)
                    .where(
                        NOTICE_JOBS.c.account == self.account,
                        NOTICE_JOBS.c.state == "sending",
                        NOTICE_JOBS.c.lease_until <= now(),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(100)
                )
            )
            .mappings()
            .all()
        )
        for job in expired:
            await db.execute(
                insert(NOTICE_RESULTS).values(
                    result_id=uuid5(job.current_attempt_id, "recovery"),
                    attempt_id=job.current_attempt_id,
                    observed_at=now(),
                    outcome="unknown",
                    applied=True,
                )
            )
            await db.execute(
                update(NOTICE_JOBS)
                .where(NOTICE_JOBS.c.job_id == job.job_id)
                .values(state="unknown")
            )
        job = (
            (
                await db.execute(
                    select(NOTICE_JOBS)
                    .where(
                        NOTICE_JOBS.c.account == self.account,
                        NOTICE_JOBS.c.state == "ready",
                        (NOTICE_JOBS.c.lease_until.is_(None))
                        | (NOTICE_JOBS.c.lease_until <= now()),
                    )
                    .order_by(NOTICE_JOBS.c.job_id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        if job is None:
            return None
        user = await db.get(UserModel, job.recipient_id)
        if (
            user is None
            or not user.telegram_id
            or (
                job.kind == "admin"
                and (not user.admin or user.status != UserStatus.ACTIVE)
            )
        ):
            await db.execute(
                update(NOTICE_JOBS)
                .where(NOTICE_JOBS.c.job_id == job.job_id)
                .values(state="obsolete")
            )
            return None
        source = await self._row(
            INBOX, INBOX.c.receipt_id == job.receipt_id, db
        )
        prefixes = {
            "ru": "Telegram подтвердил оплату услуг UMC.",
            "en": "Telegram confirmed payment for UMC services.",
            "kk": "Telegram UMC қызметтерінің төлемін растады.",
            "be": "Telegram пацвердзіў аплату паслуг UMC.",
            "uz": "Telegram UMC xizmatlari to‘lovini tasdiqladi.",
        }
        content = (
            prefixes.get(user.language, prefixes["ru"])
            + "\n"
            + str(job.order_id)
            + "\n"
            + str(Decimal(source.receipt["amount_minor"]) / 100)
            + " "
            + source.receipt["currency"]
        )
        if job.kind == "admin" and self.config.admin.admin_base_url.startswith(
            "https://"
        ):
            content += (
                "\n"
                + self.config.admin.admin_base_url.rstrip("/")
                + "/order-model/edit/"
                + str(job.order_id)
            )
        attempt = PaidNotice(
            uuid4(), job.job_id, "telegram", user.telegram_id, content
        )
        lease = now() + timedelta(minutes=2)
        await db.execute(
            insert(NOTICE_ATTEMPTS).values(
                attempt_id=attempt.attempt_id,
                job_id=job.job_id,
                prepared_at=now(),
                lease_until=lease,
                channel="telegram",
                address=attempt.address,
                text=content,
            )
        )
        await db.execute(
            update(NOTICE_JOBS)
            .where(NOTICE_JOBS.c.job_id == job.job_id)
            .values(
                state="sending",
                attempts=job.attempts + 1,
                current_attempt_id=attempt.attempt_id,
                lease_until=lease,
            )
        )
        return attempt

    async def finish_notice(self, notice, outcome, reference, *, session):
        db = _session(session)
        job = await self._row(
            NOTICE_JOBS, NOTICE_JOBS.c.job_id == notice.job_id, db, lock=True
        )
        applied = (
            job.state == "sending"
            and job.current_attempt_id == notice.attempt_id
            and job.lease_until > now()
        )
        result_id = uuid5(notice.attempt_id, digest([outcome, reference]))
        if await self._row(
            NOTICE_RESULTS, NOTICE_RESULTS.c.result_id == result_id, db
        ):
            return
        await db.execute(
            insert(NOTICE_RESULTS).values(
                result_id=result_id,
                attempt_id=notice.attempt_id,
                observed_at=now(),
                outcome=outcome,
                reference=reference,
                applied=applied,
            )
        )
        if applied:
            retry = outcome == "failed" and job.attempts < 3
            await db.execute(
                update(NOTICE_JOBS)
                .where(NOTICE_JOBS.c.job_id == job.job_id)
                .values(
                    state="ready" if retry else outcome,
                    lease_until=now() + timedelta(seconds=30)
                    if retry
                    else None,
                )
            )

    async def review_context(self, order_id, actor, *, session):
        db = _session(session)
        admin = await db.get(UserModel, actor.user_id)
        if (
            actor.platform != "telegram"
            or admin is None
            or admin.admin is not True
            or admin.status != UserStatus.ACTIVE
            or admin.telegram_id != actor.external_id
        ):
            raise PermissionError("current_admin_required")
        order = await db.get(OrderModel, order_id)
        if order is None or order.financial_version is None:
            raise LookupError("financial_order_not_found")
        value = await self._snapshot(order, db)
        receipts = (
            (
                await db.execute(
                    select(INBOX_STATE.c.state)
                    .join(INBOX, INBOX_STATE.c.receipt_id == INBOX.c.receipt_id)
                    .where(INBOX.c.order_id == order_id)
                )
            )
            .scalars()
            .all()
        )
        value["paid_receipt_count"] = len(receipts)
        value["unresolved_receipt_count"] = sum(
            state != "captured" for state in receipts
        )
        value["review_source"] = "manual_admin_review"
        value["invoice_url"] = None
        value["can_open"] = False
        return value
