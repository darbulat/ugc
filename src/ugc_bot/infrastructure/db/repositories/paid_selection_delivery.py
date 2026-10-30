"""Sorted User -> funding/history -> item -> queue locks; no external I/O."""

from dataclasses import asdict
from uuid import uuid5

from sqlalchemy import exists, insert, or_, select, text, update

from ugc_bot.application.paid_selection_delivery_ports import (
    SelectionDeliveryAttempt,
    SelectionDeliveryJob,
    SelectionDeliveryOutcome,
    SelectionDeliverySource,
)
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.identity_history_schema import (
    HISTORY_SNAPSHOT_LOCK_SQL,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ManagerOrderModel,
    OrderItemModel,
    OrderModel,
    OutboxEventModel,
    PaymentModel,
)
from ugc_bot.infrastructure.db.paid_selection_models import INTERESTS, JOBS
from ugc_bot.infrastructure.db.repositories.correction_funding import (
    require_forward_clear,
)
from ugc_bot.infrastructure.db.repositories.entitlements import _require, _row
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
    _session,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    payload_hash,
)
from ugc_bot.infrastructure.db.repositories.notice_delivery import (
    SqlAlchemyNoticeDeliveryRepository,
)
from ugc_bot.infrastructure.db.repositories.outbox import (
    _to_outbox_event_entity,
)
from ugc_bot.infrastructure.db.repositories.paid_selection import (
    SqlAlchemyPaidSelectionRepository,
    delivery_job_id,
)
from ugc_bot.infrastructure.db.repositories.selection_delivery_funding import (
    SqlAlchemySelectionFundingRepository,
)
from ugc_bot.infrastructure.db.selection_delivery_models import (
    ACCEPTED,
    ATTEMPTS,
    OUTCOMES,
)


class SqlAlchemyPaidSelectionDeliveryRepository:
    async def candidates(self, at, limit, *, session):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("selection_delivery_limit_invalid")
        result = await _session(session).scalars(
            select(JOBS.c.job_id)
            .where(
                or_(
                    JOBS.c.state == "ready",
                    (JOBS.c.state == "sending") & (JOBS.c.lease_until <= at),
                )
            )
            .order_by(JOBS.c.created_at, JOBS.c.job_id)
            .limit(limit)
        )
        return tuple(result)

    async def _interest(self, db, job_id):
        job = (
            (await db.execute(select(JOBS).where(JOBS.c.job_id == job_id)))
            .mappings()
            .one_or_none()
        )
        if job is None:
            return None, None
        interest = await _row(
            db, INTERESTS.name, "interest_id", job["interest_id"]
        )
        _require(
            job_id == delivery_job_id(interest["interest_id"])
            and job["order_id"] == interest["order_id"]
            and interest["accepted"],
            "selection_delivery_pointer_invalid",
        )
        return job, interest

    async def lock_source(self, job_id, at, *, session):
        db = _session(session)
        _, interest = await self._interest(db, job_id)
        if interest is None:
            return None
        order_id = interest["order_id"]
        users = {interest["client_id"], interest["creator_id"]}
        if interest["manager_id"] is not None:
            users.add(interest["manager_id"])
        users.update(
            await db.scalars(
                select(ManagerOrderModel.user_id).where(
                    ManagerOrderModel.order_id == order_id
                )
            )
        )
        order_client = await db.scalar(
            select(OrderModel.advertiser_id).where(
                OrderModel.order_id == order_id
            )
        )
        if order_client is not None:
            users.add(order_client)
        await SqlAlchemyPaidSelectionRepository().lock_users(
            tuple(sorted(users, key=str)), session=db
        )
        # This role table has no history writer trigger. Retain its row until
        # the final accepted fact commits, including against legacy deletes.
        await db.execute(
            select(AdvertiserProfileModel.user_id)
            .where(AdvertiserProfileModel.user_id == interest["client_id"])
            .with_for_update(read=True, key_share=True)
        )
        # Creator profile writes acquire the exclusive history barrier BEFORE
        # taking any row lock. Never take that profile row before our shared
        # barrier; the shared barrier alone freezes all its content below.
        await SqlAlchemyFinancialItemRepository().lock_order(
            order_id, session=db
        )
        await db.execute(
            select(OrderModel.order_id)
            .where(OrderModel.order_id == order_id)
            .with_for_update()
        )
        await db.execute(
            select(PaymentModel.payment_id)
            .where(PaymentModel.order_id == order_id)
            .with_for_update()
        )
        managers = tuple(
            await db.scalars(
                select(ManagerOrderModel.user_id)
                .where(ManagerOrderModel.order_id == order_id)
                .order_by(ManagerOrderModel.user_id)
                .with_for_update()
            )
        )
        _require(
            set(managers) <= users, "selection_scope_changed_retry_required"
        )
        await db.execute(text(HISTORY_SNAPSHOT_LOCK_SQL))
        item_ids = tuple(
            await db.scalars(
                select(OrderItemModel.paid_item_id)
                .where(OrderItemModel.order_id == order_id)
                .order_by(OrderItemModel.paid_item_id)
            )
        )
        for item_id in item_ids:
            await db.execute(
                select(OrderItemModel.paid_item_id)
                .where(OrderItemModel.paid_item_id == item_id)
                .with_for_update()
            )
        _, current = await self._interest(db, job_id)
        _require(current == interest, "selection_delivery_pointer_invalid")
        return await self._current(db, interest, job_id, at, users)

    async def _current(self, db, interest, job_id, at, users):
        order = await _row(db, "orders", "order_id", interest["order_id"])
        _require(
            order["advertiser_id"] in users,
            "selection_scope_changed_retry_required",
        )
        capture_event = await db.get(
            OutboxEventModel, interest["capture_event_id"]
        )
        _require(capture_event is not None, "selection_capture_source_missing")
        capture = await SqlAlchemySelectionFundingRepository().load_capture(
            _to_outbox_event_entity(capture_event), session=db
        )
        assignment = await _row(
            db, "item_assignments", "assignment_id", interest["assignment_id"]
        )
        item = await _row(
            db, "order_items", "paid_item_id", interest["paid_item_id"]
        )
        allocation_table = Base.metadata.tables["payment_item_allocations"]
        allocation = (
            (
                await db.execute(
                    select(allocation_table).where(
                        allocation_table.c.paid_item_id == item["paid_item_id"],
                        allocation_table.c.component == "selection",
                    )
                )
            )
            .mappings()
            .one()
        )
        _require(
            capture.event_id == interest["capture_event_id"]
            and capture.order_id == interest["order_id"]
            and capture.payment_id == interest["payment_id"]
            and capture.client_id == interest["client_id"]
            and capture.policy.version == interest["policy_version"]
            and interest["currency"] == "RUB"
            and assignment["paid_item_id"]
            == item["paid_item_id"]
            == interest["paid_item_id"]
            and assignment["creator_id"] == interest["creator_id"]
            and assignment["manager_id"] == interest["manager_id"]
            and assignment["valid_from"] == interest["confirmed_at"]
            and assignment["actor_id"] == interest["creator_id"]
            and item["order_id"] == interest["order_id"]
            and allocation["payment_id"] == capture.payment_id
            and allocation["currency"] == "RUB"
            and allocation["amount_minor"]
            == item["selection_minor"]
            == capture.policy.selection_minor
            and capture.captured_at <= interest["confirmed_at"] <= at,
            "selection_delivery_scope_invalid",
        )
        await require_forward_clear(item["paid_item_id"], session=db)
        profile = (
            (
                await db.execute(
                    select(BloggerProfileModel.__table__).where(
                        BloggerProfileModel.user_id == interest["creator_id"]
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        creator = await _row(db, "users", "user_id", interest["creator_id"])
        client = await _row(db, "users", "user_id", interest["client_id"])
        client_role = await db.scalar(
            select(
                exists().where(
                    AdvertiserProfileModel.user_id == interest["client_id"]
                )
            )
        )
        contact = await SqlAlchemyNoticeDeliveryRepository().contact(
            interest["client_id"], session=db
        )
        creator_contact = dict(
            username=creator["username"],
            telegram=creator["telegram"],
            phone=profile["phone"] if profile else None,
        )
        invalid = self._invalid(
            interest,
            order,
            item,
            assignment,
            profile,
            creator,
            client,
            client_role,
            contact,
            at,
        )
        delivered = await db.scalar(
            select(ACCEPTED.c.delivery_id).where(
                or_(
                    ACCEPTED.c.paid_item_id == item["paid_item_id"],
                    (ACCEPTED.c.order_id == interest["order_id"])
                    & (
                        ACCEPTED.c.instagram_user_id
                        == interest["instagram_user_id"]
                    ),
                )
            )
        )
        if delivered is not None:
            invalid = "selection_already_delivered"
        frozen = dict(
            interest=dict(interest),
            assignment=dict(assignment),
            allocation=dict(allocation),
            capture_hash=capture.source_hash,
            contact=asdict(contact) if contact else None,
            creator_contact=creator_contact,
            creator_status=str(creator["status"]),
            client_status=str(client["status"]),
            client_role=bool(client_role),
            instagram=dict(
                confirmed=profile["confirmed"],
                instagram_user_id=profile["instagram_user_id"],
                instagram_url=profile["instagram_url"],
            )
            if profile
            else None,
        )
        return SelectionDeliverySource(
            job_id,
            interest["interest_id"],
            interest["order_id"],
            interest["client_id"],
            interest["creator_id"],
            item["paid_item_id"],
            assignment["assignment_id"],
            assignment["version"],
            assignment["manager_id"],
            capture.payment_id,
            capture.event_id,
            allocation["allocation_key"],
            capture.policy.version,
            "RUB",
            interest["instagram_user_id"],
            interest["instagram_url"],
            interest["confirmed_at"],
            item["selection_due_at"],
            contact,
            creator_contact,
            payload_hash(frozen),
            invalid,
        )

    @staticmethod
    def _invalid(
        interest,
        order,
        item,
        assignment,
        profile,
        creator,
        client,
        client_role,
        contact,
        at,
    ):
        if (
            assignment["valid_to"] is not None
            or item["selection_state"] != "paid"
        ):
            return "selection_assignment_obsolete"
        if (
            order["status"] != OrderStatus.ACTIVE
            or at >= item["selection_due_at"]
        ):
            return "selection_order_unavailable"
        if not client_role or str(client["status"]) not in (
            "active",
            "pause",
            "bot_blocked",
        ):
            return "selection_client_role_revoked"
        if (
            profile is None
            or not profile["confirmed"]
            or str(creator["status"]) not in ("active", "pause")
            or not profile["instagram_user_id"]
            or profile["instagram_user_id"].strip()
            != interest["instagram_user_id"]
            or profile["instagram_url"] != interest["instagram_url"]
        ):
            return "selection_creator_verification_changed"
        if (
            contact is None
            or not contact.address
            or contact.channel not in ("telegram", "max")
            or contact.status not in ("active", "pause")
        ):
            return "selection_client_contact_unavailable"
        return None

    async def job(self, job_id, *, session):
        row = (
            (
                await _session(session).execute(
                    select(JOBS)
                    .where(JOBS.c.job_id == job_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        return SelectionDeliveryJob(**row) if row is not None else None

    async def save_job(self, job, *, session):
        values = asdict(job)
        values.pop("job_id")
        await _session(session).execute(
            update(JOBS).where(JOBS.c.job_id == job.job_id).values(**values)
        )

    async def save_attempt(self, attempt, *, session):
        await _session(session).execute(
            insert(ATTEMPTS).values(**asdict(attempt))
        )

    async def attempt(self, attempt_id, *, session):
        row = (
            (
                await _session(session).execute(
                    select(ATTEMPTS).where(ATTEMPTS.c.attempt_id == attempt_id)
                )
            )
            .mappings()
            .one()
        )
        return SelectionDeliveryAttempt(**row)

    async def outcome(self, outcome_id, *, session):
        row = (
            (
                await _session(session).execute(
                    select(OUTCOMES).where(OUTCOMES.c.outcome_id == outcome_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return SelectionDeliveryOutcome(**row) if row is not None else None

    async def save_outcome(self, outcome, *, session):
        await _session(session).execute(
            insert(OUTCOMES).values(**asdict(outcome))
        )

    async def receipt_used(self, channel, reference, *, session):
        db = _session(session)
        # Provider IDs are global within a channel. Coordinate even if two
        # otherwise independent orders receive the same erroneous receipt.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "selection-provider-receipt:" + channel + ":" + reference},
        )
        return bool(
            await db.scalar(
                select(
                    exists().where(
                        ACCEPTED.c.channel == channel,
                        ACCEPTED.c.provider_reference == reference,
                    )
                )
            )
        )

    async def accept(self, attempt, source, outcome, *, session):
        db = _session(session)
        values = {
            key: getattr(source, key)
            for key in (
                "job_id",
                "interest_id",
                "order_id",
                "client_id",
                "creator_id",
                "paid_item_id",
                "assignment_id",
                "payment_id",
                "capture_event_id",
                "allocation_key",
                "policy_version",
                "currency",
                "instagram_user_id",
                "source_hash",
            )
        }
        await db.execute(
            insert(ACCEPTED).values(
                **values,
                delivery_id=uuid5(source.interest_id, "accepted-selection"),
                outcome_id=outcome.outcome_id,
                attempt_id=attempt.attempt_id,
                amount_minor=await db.scalar(
                    select(
                        Base.metadata.tables[
                            "payment_item_allocations"
                        ].c.amount_minor
                    ).where(
                        Base.metadata.tables[
                            "payment_item_allocations"
                        ].c.allocation_key
                        == source.allocation_key
                    )
                ),
                accepted_at=outcome.recorded_at,
                channel=attempt.channel,
                provider_reference=outcome.provider_reference,
            )
        )
        result = await db.execute(
            update(OrderItemModel)
            .where(
                OrderItemModel.paid_item_id == source.paid_item_id,
                OrderItemModel.selection_state == "paid",
            )
            .values(selection_state="delivered")
        )
        _require(
            getattr(result, "rowcount", 0) == 1,
            "selection_delivery_projection_changed",
        )
