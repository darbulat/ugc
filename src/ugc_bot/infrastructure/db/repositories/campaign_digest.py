"""User -> order -> history -> item barriers, then the delivery projection."""

from dataclasses import asdict
from datetime import timedelta
from uuid import uuid4, uuid5

from sqlalchemy import exists, insert, or_, select, text, union, update

from ugc_bot.application.campaign_digest_ports import (
    DigestAttempt,
    DigestSource,
)
from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.infrastructure.db.campaign_digest_models import (
    ATTEMPTS,
    JOBS,
    OUTCOMES,
    REQUESTS,
)
from ugc_bot.infrastructure.db.identity_history_schema import (
    HISTORY_SNAPSHOT_LOCK_SQL,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    InteractionModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
    PaymentItemAllocationModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.campaign_summary import (
    SqlAlchemyCampaignSummaryRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
    _session,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import payload_hash
from ugc_bot.infrastructure.db.repositories.notice_delivery import (
    SqlAlchemyNoticeDeliveryRepository,
)


async def _row(db, statement):
    return (await db.execute(statement)).mappings().one()


class SqlAlchemyCampaignDigestRepository:
    @staticmethod
    def _eligible(at):
        # A digest is informational. Eligibility requires actual captured item
        # allocation, or an existing due legacy interaction, never a quote.
        financial = exists().where(
            OrderItemModel.order_id == OrderModel.order_id,
            OrderItemModel.captured_at.is_not(None),
            OrderItemModel.captured_at <= at,
            OrderItemModel.paid_item_id
            == PaymentItemAllocationModel.paid_item_id,
            PaymentItemAllocationModel.payment_id == PaymentModel.payment_id,
            PaymentModel.order_id == OrderModel.order_id,
            PaymentModel.captured_minor.is_not(None),
            PaymentModel.financial_version == OrderModel.financial_version,
            PaymentModel.status == "paid",
            OrderItemModel.policy_version == OrderModel.financial_version,
            OrderItemModel.selection_state.in_(("paid", "delivered")),
            PaymentItemAllocationModel.order_id == OrderModel.order_id,
            PaymentItemAllocationModel.component == "selection",
            PaymentItemAllocationModel.currency == OrderItemModel.currency,
            PaymentItemAllocationModel.amount_minor
            == OrderItemModel.selection_minor,
        )
        legacy = exists().where(
            InteractionModel.order_id == OrderModel.order_id,
            InteractionModel.advertiser_id == OrderModel.advertiser_id,
            InteractionModel.status == "pending",
            InteractionModel.next_check_at <= at,
        )
        return (OrderModel.status != "deleted") & or_(
            OrderModel.financial_version.is_not(None) & financial,
            OrderModel.financial_version.is_(None) & legacy,
        )

    async def due_scopes(self, at, limit, *, session):
        clients = select(
            OrderModel.order_id, OrderModel.advertiser_id.label("recipient_id")
        ).where(
            self._eligible(at),
            exists().where(
                AdvertiserProfileModel.user_id == OrderModel.advertiser_id
            ),
        )
        manager_scope = or_(
            OrderModel.financial_version.is_not(None)
            & exists().where(
                ItemAssignmentModel.manager_id == ManagerOrderModel.user_id,
                ItemAssignmentModel.valid_to.is_(None),
                ItemAssignmentModel.paid_item_id == OrderItemModel.paid_item_id,
                OrderItemModel.order_id == OrderModel.order_id,
            ),
            OrderModel.financial_version.is_(None)
            & exists().where(
                OfferDispatchModel.order_id == OrderModel.order_id,
                OfferDispatchModel.manager_id == ManagerOrderModel.user_id,
                OfferDispatchModel.in_offer.is_(True),
                OfferDispatchModel.accepted.is_(True),
                OfferDispatchModel.blogger_id == InteractionModel.blogger_id,
                InteractionModel.order_id == OrderModel.order_id,
                InteractionModel.advertiser_id == OrderModel.advertiser_id,
                InteractionModel.status != "deleted",
            ),
        )
        managers = (
            select(
                OrderModel.order_id,
                ManagerOrderModel.user_id.label("recipient_id"),
            )
            .join(
                ManagerOrderModel,
                ManagerOrderModel.order_id == OrderModel.order_id,
            )
            .where(self._eligible(at), manager_scope)
        )
        scopes = union(clients, managers).subquery()
        recent = exists().where(
            REQUESTS.c.order_id == scopes.c.order_id,
            REQUESTS.c.recipient_id == scopes.c.recipient_id,
            REQUESTS.c.created_at > at - timedelta(days=7),
        )
        rows = await _session(session).execute(
            select(scopes)
            .join(UserModel, UserModel.user_id == scopes.c.recipient_id)
            .where(
                ~recent,
                UserModel.status == "active",
                or_(
                    (UserModel.messenger_type == "telegram")
                    & UserModel.telegram_id.op("~")(r"^[1-9][0-9]*$"),
                    (UserModel.messenger_type == "max")
                    & or_(
                        UserModel.max_chat_id.op("~")(r"^[1-9][0-9]*$"),
                        UserModel.max_id.op("~")(r"^[1-9][0-9]*$")
                        & UserModel.max_chat_id.is_(None),
                    ),
                ),
            )
            .order_by(scopes.c.order_id, scopes.c.recipient_id)
            .limit(limit)
        )
        return tuple(rows)

    async def lock_source(self, order_id, recipient_id, at, *, session):
        db = _session(session)
        initial_client = await db.scalar(
            select(OrderModel.advertiser_id).where(
                OrderModel.order_id == order_id
            )
        )
        if initial_client is None:
            return None
        for user_id in sorted({initial_client, recipient_id}, key=str):
            await db.execute(
                select(UserModel.user_id)
                .where(UserModel.user_id == user_id)
                .with_for_update(read=True)
            )
        await SqlAlchemyFinancialItemRepository().lock_order(
            order_id, session=db
        )
        order = await db.scalar(
            select(OrderModel)
            .where(OrderModel.order_id == order_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if order is None or order.advertiser_id != initial_client:
            return None
        await db.execute(
            select(AdvertiserProfileModel.user_id)
            .where(AdvertiserProfileModel.user_id == initial_client)
            .with_for_update(read=True, key_share=True)
        )
        await db.execute(
            select(ManagerOrderModel.user_id)
            .where(
                ManagerOrderModel.order_id == order_id,
                ManagerOrderModel.user_id == recipient_id,
            )
            .with_for_update(read=True, key_share=True)
        )
        await db.execute(text(HISTORY_SNAPSHOT_LOCK_SQL))
        item_ids = tuple(
            await db.scalars(
                select(OrderItemModel.paid_item_id)
                .where(OrderItemModel.order_id == order_id)
                .order_by(OrderItemModel.paid_item_id)
                .with_for_update(read=True)
            )
        )
        # Legacy status writers use these exact rows, without the item barrier.
        interactions = (
            (
                await db.execute(
                    select(InteractionModel.__table__)
                    .where(InteractionModel.order_id == order_id)
                    .order_by(InteractionModel.interaction_id)
                    .with_for_update(read=True)
                )
            )
            .mappings()
            .all()
        )
        await db.execute(
            select(OfferDispatchModel.order_id)
            .where(OfferDispatchModel.order_id == order_id)
            .order_by(OfferDispatchModel.blogger_id)
            .with_for_update(read=True)
        )
        contact = await SqlAlchemyNoticeDeliveryRepository().contact(
            recipient_id, session=db
        )
        if (
            contact is None
            or contact.status != "active"
            or contact.channel not in ("telegram", "max")
            or not contact.address
            or not str(contact.address).isdigit()
            or int(contact.address) <= 0
        ):
            return None
        if not await db.scalar(
            select(
                exists().where(
                    OrderModel.order_id == order_id, self._eligible(at)
                )
            )
        ):
            return None
        try:
            summary = await SqlAlchemyCampaignSummaryRepository().view(
                order_id, recipient_id, session=db
            )
        except (LookupError, PermissionError, ValueError):
            return None
        if not summary["total"]:
            return None
        # Exact assignment and legacy source identities prevent same-count
        # replacements from silently changing a prepared recipient's context.
        assignments = (
            (
                await db.execute(
                    select(ItemAssignmentModel.__table__)
                    .where(ItemAssignmentModel.paid_item_id.in_(item_ids))
                    .order_by(ItemAssignmentModel.assignment_id)
                )
            )
            .mappings()
            .all()
        )
        fingerprint = payload_hash(
            canonical(
                {
                    "summary": summary,
                    "contact": asdict(contact),
                    "client": initial_client,
                    "items": item_ids,
                    "assignments": [dict(a) for a in assignments],
                    "interactions": [dict(i) for i in interactions],
                }
            )
        )
        return DigestSource(
            order_id, recipient_id, summary, contact, fingerprint
        )

    async def enqueue(self, source, at, *, session):
        db = _session(session)
        latest = await db.scalar(
            select(REQUESTS.c.created_at)
            .where(
                REQUESTS.c.order_id == source.order_id,
                REQUESTS.c.recipient_id == source.recipient_id,
            )
            .order_by(REQUESTS.c.created_at.desc())
            .limit(1)
        )
        week_start = (at - timedelta(days=at.weekday())).date()
        if (
            latest is not None and latest > at - timedelta(days=7)
        ) or await db.scalar(
            select(
                exists().where(
                    REQUESTS.c.order_id == source.order_id,
                    REQUESTS.c.recipient_id == source.recipient_id,
                    REQUESTS.c.week_start == week_start,
                )
            )
        ):
            return None
        request_id = uuid4()
        await db.execute(
            insert(REQUESTS).values(
                request_id=request_id,
                order_id=source.order_id,
                recipient_id=source.recipient_id,
                week_start=week_start,
                created_at=at,
                source=canonical(source.summary),
                source_hash=source.fingerprint,
            )
        )
        await db.execute(
            insert(JOBS).values(request_id=request_id, state="ready")
        )
        return request_id

    async def candidates(self, at, limit, *, session):
        return tuple(
            await _session(session).scalars(
                select(JOBS.c.request_id)
                .join(REQUESTS, REQUESTS.c.request_id == JOBS.c.request_id)
                .where(
                    or_(
                        JOBS.c.state == "ready",
                        (JOBS.c.state == "sending")
                        & (JOBS.c.lease_until <= at),
                    )
                )
                .order_by(REQUESTS.c.created_at, JOBS.c.request_id)
                .limit(limit)
            )
        )

    async def scope(self, request_id, *, session):
        row = await _row(
            _session(session),
            select(REQUESTS.c.order_id, REQUESTS.c.recipient_id).where(
                REQUESTS.c.request_id == request_id
            ),
        )
        return row["order_id"], row["recipient_id"]

    async def job(self, request_id, *, session):
        return dict(
            await _row(
                _session(session),
                select(JOBS)
                .where(JOBS.c.request_id == request_id)
                .with_for_update(),
            )
        )

    async def save_job(self, request_id, state, *, session, **values):
        await _session(session).execute(
            update(JOBS)
            .where(JOBS.c.request_id == request_id)
            .values(state=state, **values)
        )

    async def save_attempt(self, attempt, *, session):
        values = asdict(attempt)
        values["source"] = canonical(values["source"])
        await _session(session).execute(insert(ATTEMPTS).values(**values))

    async def attempt(self, request_id, *, session):
        row = (
            (
                await _session(session).execute(
                    select(ATTEMPTS).where(ATTEMPTS.c.request_id == request_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return DigestAttempt(**row) if row else None

    async def outcome(self, attempt_id, kind, *, session):
        return (
            (
                await _session(session).execute(
                    select(OUTCOMES).where(
                        OUTCOMES.c.attempt_id == attempt_id,
                        OUTCOMES.c.kind == kind,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    async def receipt_used(self, channel, reference, *, session):
        db = _session(session)
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"campaign-digest-receipt:{channel}:{reference}"},
        )
        return bool(
            await db.scalar(
                select(
                    exists().where(
                        OUTCOMES.c.channel == channel,
                        OUTCOMES.c.provider_reference == reference,
                        OUTCOMES.c.kind == "transport",
                        OUTCOMES.c.status == "accepted",
                    )
                )
            )
        )

    async def save_outcome(
        self,
        request_id,
        attempt_id,
        kind,
        status,
        at,
        *,
        session,
        reference=None,
        reason=None,
        applied=False,
    ):
        identity = attempt_id or request_id
        db = _session(session)
        channel = (
            await db.scalar(
                select(ATTEMPTS.c.channel).where(
                    ATTEMPTS.c.attempt_id == attempt_id
                )
            )
            if attempt_id
            else None
        )
        await db.execute(
            insert(OUTCOMES).values(
                outcome_id=uuid5(identity, kind),
                request_id=request_id,
                attempt_id=attempt_id,
                kind=kind,
                status=status,
                recorded_at=at,
                channel=channel,
                provider_reference=reference,
                reason=reason,
                applied=applied,
            )
        )
