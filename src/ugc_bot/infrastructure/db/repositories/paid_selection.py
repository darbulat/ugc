"""User -> order/funding -> history -> item lock order for paid interests."""

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import exists, func, insert, select, text, update

from ugc_bot.application.paid_selection_ports import SelectionInterest
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.db.identity_history_schema import (
    HISTORY_SNAPSHOT_LOCK_SQL,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
    OutboxEventModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.paid_selection_models import INTERESTS, JOBS
from ugc_bot.infrastructure.db.repositories.entitlements import (
    SqlAlchemyClientEntitlementRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
    _session,
)
from ugc_bot.infrastructure.db.repositories.item_assignments import (
    SqlAlchemyItemAssignmentRepository,
)
from ugc_bot.infrastructure.db.repositories.outbox import (
    _to_outbox_event_entity,
)


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def delivery_job_id(interest_id):
    return uuid5(interest_id, "selection-delivery")


class SqlAlchemyPaidSelectionRepository:
    async def count_accepted(self, order_id, *, session):
        return await _session(session).scalar(
            select(func.count())
            .select_from(INTERESTS)
            .where(
                INTERESTS.c.order_id == order_id, INTERESTS.c.accepted.is_(True)
            )
        )

    async def discover(self, order_id, *, session):
        db = _session(session)
        row = (
            await db.execute(
                select(
                    OrderModel.advertiser_id,
                    OrderModel.financial_version,
                    OrderModel.complimentary,
                ).where(OrderModel.order_id == order_id)
            )
        ).one_or_none()
        if row is None:
            raise ValueError("order_not_found")
        if row.financial_version is None or row.complimentary:
            return None
        managers = await db.scalars(
            select(ManagerOrderModel.user_id).where(
                ManagerOrderModel.order_id == order_id
            )
        )
        return tuple(sorted({row.advertiser_id, *managers}, key=str))

    async def lock_users(self, users, *, session):
        db = _session(session)
        for user_id in sorted(set(users), key=str):
            found = await db.scalar(
                select(UserModel.user_id)
                .where(UserModel.user_id == user_id)
                .with_for_update(key_share=True)
            )
            _require(found is not None, "selection_user_missing")

    async def _funding(self, order_id, *, session):
        db = _session(session)
        rows = (
            await db.scalars(
                select(OutboxEventModel).where(
                    OutboxEventModel.aggregate_type == "order",
                    OutboxEventModel.aggregate_id == str(order_id),
                    OutboxEventModel.event_type
                    == "financial.client_snapshot_requested",
                )
            )
        ).all()
        _require(len(rows) == 1, "confirmed_capture_required")
        return await SqlAlchemyClientEntitlementRepository().load_capture(
            _to_outbox_event_entity(rows[0]), session=db
        )

    async def confirm(
        self, order_id, creator_id, locked_users, now, *, session
    ):
        db = _session(session)
        await SqlAlchemyFinancialItemRepository().lock_order(
            order_id, session=db
        )
        order = (
            (
                await db.execute(
                    select(OrderModel.__table__)
                    .where(OrderModel.order_id == order_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one()
        )
        # Coordination rows precede the shared identity barrier and item rows.
        await db.execute(
            select(PaymentModel.payment_id)
            .where(PaymentModel.order_id == order_id)
            .with_for_update()
        )
        manager_rows = (
            (
                await db.execute(
                    select(ManagerOrderModel.__table__)
                    .where(ManagerOrderModel.order_id == order_id)
                    .order_by(ManagerOrderModel.user_id)
                    .with_for_update()
                )
            )
            .mappings()
            .all()
        )
        current_users = {
            order["advertiser_id"],
            creator_id,
            *(r["user_id"] for r in manager_rows),
        }
        _require(
            current_users <= set(locked_users),
            "selection_scope_changed_retry_required",
        )
        _require(
            order["financial_version"] is not None
            and not order["complimentary"],
            "selection_scope_changed_retry_required",
        )
        # Preserve the current client role through commit. Take this child-row
        # barrier before history, so a role writer needing history can finish.
        client_role = await db.scalar(
            select(AdvertiserProfileModel.user_id)
            .where(AdvertiserProfileModel.user_id == order["advertiser_id"])
            .with_for_update(read=True, key_share=True)
        )
        _require(client_role is not None, "selection_client_role_required")
        await db.execute(text(HISTORY_SNAPSHOT_LOCK_SQL))
        for item_id in await db.scalars(
            select(OrderItemModel.paid_item_id)
            .where(OrderItemModel.order_id == order_id)
            .order_by(OrderItemModel.paid_item_id)
        ):
            await db.execute(
                select(OrderItemModel.paid_item_id)
                .where(OrderItemModel.paid_item_id == item_id)
                .with_for_update()
            )
        at = utc(now())
        users = (
            await db.execute(
                select(UserModel.user_id, UserModel.status).where(
                    UserModel.user_id.in_(current_users)
                )
            )
        ).all()
        statuses = {row.user_id: str(row.status) for row in users}
        _require(
            statuses.get(creator_id) in ("active", "pause"),
            "selection_creator_inactive",
        )
        _require(
            statuses.get(order["advertiser_id"])
            in ("active", "pause", "bot_blocked"),
            "selection_client_inactive",
        )
        _require(
            creator_id != order["advertiser_id"],
            "selection_distinct_parties_required",
        )
        profile = (
            (
                await db.execute(
                    select(BloggerProfileModel.__table__).where(
                        BloggerProfileModel.user_id == creator_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        _require(
            profile is not None
            and profile["confirmed"]
            and profile["instagram_user_id"]
            and profile["instagram_user_id"].strip(),
            "selection_verified_creator_required",
        )
        assert profile is not None  # required above; narrow the SQL row type
        previous = (
            (
                await db.execute(
                    select(INTERESTS).where(
                        INTERESTS.c.order_id == order_id,
                        INTERESTS.c.creator_id == creator_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if previous is not None:
            return await self._result(previous, session=db)
        _require(
            not await db.scalar(
                select(
                    exists().where(
                        INTERESTS.c.order_id == order_id,
                        INTERESTS.c.instagram_user_id
                        == profile["instagram_user_id"].strip(),
                    )
                )
            ),
            "selection_identity_already_interested",
        )
        capture = await self._funding(order_id, session=db)
        _require(
            order["status"] == OrderStatus.ACTIVE, "selection_order_not_active"
        )
        items = (
            (
                await db.execute(
                    select(OrderItemModel.__table__)
                    .where(OrderItemModel.order_id == order_id)
                    .order_by(OrderItemModel.ordinal)
                )
            )
            .mappings()
            .all()
        )
        _require(
            len(items) == order["bloggers_needed"],
            "selection_purchased_pool_mismatch",
        )
        _require(
            all(i["selection_due_at"] > at for i in items),
            "selection_due_elapsed",
        )
        item = None
        for candidate in items:
            if not await db.scalar(
                select(
                    exists().where(
                        ItemAssignmentModel.paid_item_id
                        == candidate["paid_item_id"]
                    )
                )
            ):
                item = candidate
                break
        # A completed initial assignment is never silently recycled here.
        accepted, assignment, manager = item is not None, None, None
        if item is not None:
            _require(
                item["selection_state"] == "paid",
                "selection_position_unavailable",
            )
            if item["accompaniment_minor"]:
                managers = [
                    r["user_id"]
                    for r in manager_rows
                    if r["created_at"] <= at
                    and statuses.get(r["user_id"]) in ("active", "pause")
                ]
                if managers:
                    manager = managers[
                        order["last_round_robin_index"] % len(managers)
                    ]
            assignment = await SqlAlchemyItemAssignmentRepository().replace(
                paid_item_id=item["paid_item_id"],
                expected_version=0,
                creator_id=creator_id,
                manager_id=manager,
                actor_id=creator_id,
                reason="creator confirmed interest in captured selection",
                at=at,
                session=db,
            )
        interest_id = uuid5(
            NAMESPACE_URL, f"umc:selection-interest:{order_id}:{creator_id}"
        )
        values = dict(
            interest_id=interest_id,
            order_id=order_id,
            creator_id=creator_id,
            client_id=order["advertiser_id"],
            payment_id=capture.payment_id,
            capture_event_id=capture.event_id,
            policy_version=capture.policy.version,
            currency="RUB",
            confirmed_at=at,
            instagram_user_id=profile["instagram_user_id"].strip(),
            instagram_url=profile["instagram_url"],
            accepted=accepted,
            paid_item_id=item["paid_item_id"] if item else None,
            assignment_id=assignment.assignment_id if assignment else None,
            manager_id=manager,
        )
        await db.execute(insert(INTERESTS).values(**values))
        if accepted:
            await db.execute(
                insert(JOBS).values(
                    job_id=delivery_job_id(interest_id),
                    interest_id=interest_id,
                    order_id=order_id,
                    created_at=at,
                    state="ready",
                )
            )
        await self._record_dispatch(
            order_id, creator_id, accepted, manager, at, session=db
        )
        if manager is not None:
            await db.execute(
                update(OrderModel)
                .where(OrderModel.order_id == order_id)
                .values(
                    last_round_robin_index=order["last_round_robin_index"] + 1,
                    updated_at=at,
                )
            )
        return await self._result(values, session=db)

    @staticmethod
    async def _record_dispatch(
        order_id, creator_id, accepted, manager, at, *, session
    ):
        db = session
        dispatch = (
            (
                await db.execute(
                    select(OfferDispatchModel.__table__).where(
                        OfferDispatchModel.order_id == order_id,
                        OfferDispatchModel.blogger_id == creator_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        dispatch_values = dict(
            accepted=True, in_offer=accepted, manager_id=manager, updated_at=at
        )
        if dispatch is None:
            await db.execute(
                insert(OfferDispatchModel).values(
                    order_id=order_id,
                    blogger_id=creator_id,
                    created_at=at,
                    **dispatch_values,
                )
            )
        else:
            _require(
                dispatch["accepted"] is None,
                "selection_untracked_response_requires_review",
            )
            await db.execute(
                update(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.blogger_id == creator_id,
                )
                .values(**dispatch_values)
            )

    @staticmethod
    async def _result(row, *, session):
        job = (
            await session.execute(
                select(JOBS.c.job_id, JOBS.c.state).where(
                    JOBS.c.interest_id == row["interest_id"]
                )
            )
        ).one_or_none()
        keys = (
            "interest_id",
            "order_id",
            "creator_id",
            "client_id",
            "confirmed_at",
            "instagram_user_id",
            "instagram_url",
            "accepted",
            "paid_item_id",
            "assignment_id",
            "manager_id",
        )
        return SelectionInterest(
            **{key: row[key] for key in keys},
            job_id=job.job_id if job else None,
            delivery_state=job.state if job else "waitlisted",
        )
