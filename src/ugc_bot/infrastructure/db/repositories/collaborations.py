"""Item-serialized lifecycle persistence; no commits, wallet locks or sends."""

from dataclasses import asdict

from sqlalchemy import exists, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ugc_bot.application.collaboration_ports import (
    CollaborationActor,
    CollaborationEvent,
    CollaborationNotice,
    CollaborationPrincipalScope,
    CollaborationScope,
    next_transition_at,
    record_from_payload,
    record_payload,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.infrastructure.db.collaboration_models import (
    CollaborationEventModel,
    CollaborationModel,
    CollaborationNoticeModel,
    CollaborationReleaseScheduleModel,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    OrderItemModel,
    OrderModel,
    OutboxEventModel,
    PaymentItemAllocationModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyCollaborationRepository:
    @staticmethod
    def _root_transaction(db, *, allow_nested=True):
        root = db.sync_session.get_transaction()
        if (
            root is None
            or not root.is_active
            or (not allow_nested and db.in_nested_transaction())
        ):
            raise ValueError("caller_transaction_required")
        return root

    @classmethod
    def _require_prepared(cls, db, assignment_id, expected_scope):
        root = cls._root_transaction(db)
        if expected_scope is not None:
            if (
                expected_scope.owner_session is not db
                or expected_scope.root_transaction is not root
            ):
                raise ValueError("caller_transaction_required")
            if expected_scope.assignment_id != assignment_id:
                raise ValueError("collaboration_scope_changed")

    @staticmethod
    async def _source_identity(assignment_id, *, session):
        assignment = ItemAssignmentModel.__table__
        item = OrderItemModel.__table__
        order = OrderModel.__table__
        return (
            (
                await session.execute(
                    select(
                        assignment.c.assignment_id,
                        assignment.c.paid_item_id,
                        item.c.order_id,
                        order.c.advertiser_id.label("client_id"),
                        assignment.c.creator_id,
                        assignment.c.manager_id,
                    )
                    .join(
                        item, item.c.paid_item_id == assignment.c.paid_item_id
                    )
                    .join(order, order.c.order_id == item.c.order_id)
                    .where(assignment.c.assignment_id == assignment_id)
                )
            )
            .mappings()
            .one_or_none()
        )

    async def prepare_principal_scope(
        self,
        assignment_id,
        actor_id,
        principal,
        *,
        session,
    ):
        db = _session(session)
        root = self._root_transaction(db, allow_nested=False)
        if (
            not isinstance(principal, AuthenticatedMessengerPrincipal)
            or principal.user_id != actor_id
        ):
            raise ValueError("financial_principal_changed")
        source = await self._source_identity(assignment_id, session=db)
        user_ids = tuple(
            sorted(
                {actor_id}
                if source is None
                else {actor_id, source["client_id"], source["creator_id"]}
                | ({source["manager_id"]} if source["manager_id"] else set())
            )
        )
        prepared = (
            CollaborationPrincipalScope(
                **source,
                actor_id=actor_id,
                user_ids=user_ids,
                owner_session=db,
                root_transaction=root,
            )
            if source is not None
            else None
        )
        users = {}
        for user_id in user_ids:
            users[user_id] = (
                await db.execute(
                    select(
                        UserModel.user_id,
                        UserModel.telegram_id,
                        UserModel.max_id,
                    )
                    .where(UserModel.user_id == user_id)
                    .with_for_update(key_share=True)
                )
            ).one_or_none()
        actor = users[actor_id]
        require_current_principal(
            principal,
            actor_id,
            actor.user_id if actor else None,
            actor.telegram_id if actor else None,
            actor.max_id if actor else None,
        )
        # An initially absent assignment cannot appear through a later load.
        if prepared is None:
            return None
        if any(user is None for user in users.values()):
            raise ValueError("collaboration_scope_changed")
        await self.lock_scope(
            assignment_id,
            session=db,
            expected_scope=prepared,
        )
        return prepared

    async def lock_scope(
        self,
        assignment_id,
        *,
        session,
        expected_scope=None,
    ):
        db = _session(session)
        self._require_prepared(db, assignment_id, expected_scope)
        assignment = ItemAssignmentModel.__table__
        item = OrderItemModel.__table__
        order = OrderModel.__table__
        item_id = await db.scalar(
            select(assignment.c.paid_item_id).where(
                assignment.c.assignment_id == assignment_id
            )
        )
        if item_id is None:
            raise ValueError(
                "collaboration_scope_changed"
                if expected_scope
                else "assignment_not_found"
            )
        if (
            expected_scope is not None
            and item_id != expected_scope.paid_item_id
        ):
            raise ValueError("collaboration_scope_changed")
        await db.execute(
            select(item.c.paid_item_id)
            .where(item.c.paid_item_id == item_id)
            .with_for_update()
        )
        # Reload core rows after the item lock; do not reuse stale ORM state.
        row = (
            (
                await db.execute(
                    select(
                        assignment,
                        item.c.order_id,
                        item.c.captured_at,
                        item.c.policy_version,
                        item.c.selection_minor,
                        order.c.advertiser_id,
                        order.c.financial_version,
                    )
                    .join(
                        item, item.c.paid_item_id == assignment.c.paid_item_id
                    )
                    .join(order, order.c.order_id == item.c.order_id)
                    .where(assignment.c.assignment_id == assignment_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ValueError(
                "collaboration_scope_changed"
                if expected_scope
                else "assignment_not_found"
            )
        if expected_scope is not None and expected_scope.source_identity != (
            row["assignment_id"],
            row["paid_item_id"],
            row["order_id"],
            row["advertiser_id"],
            row["creator_id"],
            row["manager_id"],
        ):
            raise ValueError("collaboration_scope_changed")
        funded = await db.scalar(
            select(
                exists().where(
                    PaymentItemAllocationModel.paid_item_id == item_id,
                    PaymentItemAllocationModel.order_id == row["order_id"],
                    PaymentItemAllocationModel.component == "selection",
                    PaymentItemAllocationModel.currency == "RUB",
                    PaymentItemAllocationModel.amount_minor
                    == row["selection_minor"],
                    PaymentItemAllocationModel.payment_id
                    == PaymentModel.payment_id,
                    PaymentModel.order_id == row["order_id"],
                    PaymentModel.currency == "RUB",
                    PaymentModel.captured_minor.is_not(None),
                    PaymentModel.financial_version == row["policy_version"],
                )
            )
        )
        return CollaborationScope(
            assignment_id=assignment_id,
            paid_item_id=item_id,
            order_id=row["order_id"],
            client_id=row["advertiser_id"],
            creator_id=row["creator_id"],
            manager_id=row["manager_id"],
            policy_version=row["policy_version"]
            if row["financial_version"] == row["policy_version"]
            else None,
            captured_at=row["captured_at"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            selection_funded=bool(funded),
        )

    async def load_actor(self, actor_id, *, session):
        db = _session(session)
        row = await db.get(UserModel, actor_id, populate_existing=True)
        if row is None:
            return None
        client = await db.scalar(
            select(exists().where(AdvertiserProfileModel.user_id == actor_id))
        )
        creator = await db.scalar(
            select(exists().where(BloggerProfileModel.user_id == actor_id))
        )
        manager_orders = tuple(
            await db.scalars(
                select(ManagerOrderModel.order_id).where(
                    ManagerOrderModel.user_id == actor_id
                )
            )
        )
        return CollaborationActor(
            actor_id,
            str(row.status),
            bool(client),
            bool(creator),
            row.admin,
            manager_orders,
            row.telegram_id,
            row.max_id,
        )

    async def get(self, assignment_id, *, session):
        row = await _session(session).scalar(
            select(CollaborationModel.record_payload)
            .where(CollaborationModel.assignment_id == assignment_id)
            .with_for_update()
        )
        return record_from_payload(row) if row is not None else None

    async def get_command(self, assignment_id, operation_key, *, session):
        row = (
            (
                await _session(session).execute(
                    select(CollaborationEventModel.__table__).where(
                        CollaborationEventModel.assignment_id == assignment_id,
                        CollaborationEventModel.operation_key == operation_key,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return CollaborationEvent(
            row["event_id"],
            row["assignment_id"],
            row["operation_key"],
            row["payload_hash"],
            row["event_type"],
            row["actor_id"],
            row["system_actor"],
            row["parameters"],
            record_from_payload(row["result_payload"]),
            row["occurred_at"],
        )

    async def get_notice(self, notice_id, *, session):
        row = (
            (
                await _session(session).execute(
                    select(CollaborationNoticeModel.__table__).where(
                        CollaborationNoticeModel.notice_id == notice_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return CollaborationNotice(**row) if row is not None else None

    async def list_due(self, at, limit, *, session):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid_batch_limit")
        payloads = await _session(session).scalars(
            select(CollaborationModel.record_payload)
            .join(
                ItemAssignmentModel,
                ItemAssignmentModel.assignment_id
                == CollaborationModel.assignment_id,
            )
            .where(
                CollaborationModel.next_transition_at <= at,
                ItemAssignmentModel.valid_to.is_(None),
            )
            .order_by(
                CollaborationModel.next_transition_at,
                CollaborationModel.assignment_id,
            )
            .limit(limit)
        )
        return tuple(record_from_payload(payload) for payload in payloads)

    async def persist(self, event, *, notices, schedule, session):
        db = _session(session)
        record = event.result
        work = record.collaboration
        payload = record_payload(record)
        values = dict(
            assignment_id=event.assignment_id,
            paid_item_id=record.paid_item_id,
            order_id=record.order_id,
            currency="RUB",
            client_id=work.client_id,
            creator_id=work.creator_id,
            manager_id=work.manager_id,
            policy_version=record.policy_version,
            state=work.state.value,
            version=record.version,
            due_at=work.due_at,
            next_transition_at=next_transition_at(work),
            record_payload=payload,
            updated_at=record.updated_at,
        )
        table = CollaborationModel.__table__
        if record.version == 1:
            await db.execute(insert(table).values(**values))
        else:
            result = await db.execute(
                update(table)
                .where(
                    table.c.assignment_id == event.assignment_id,
                    table.c.version == record.version - 1,
                )
                .values(**values)
            )
            if result.rowcount != 1:
                raise ValueError("collaboration_version_conflict")
        await db.execute(
            insert(CollaborationEventModel).values(
                event_id=event.event_id,
                assignment_id=event.assignment_id,
                operation_key=event.operation_key,
                version=record.version,
                payload_hash=event.payload_hash,
                event_type=event.event_type,
                actor_id=event.actor_id,
                system_actor=event.system_actor,
                parameters=event.parameters,
                result_payload=payload,
                occurred_at=event.occurred_at,
            )
        )
        await self._outbox(
            event.event_id,
            event.event_type,
            event.assignment_id,
            {"collaboration_event_id": str(event.event_id)},
            event.occurred_at,
            session=db,
        )
        for notice in notices:
            inserted = await db.scalar(
                pg_insert(CollaborationNoticeModel)
                .values(**asdict(notice))
                .on_conflict_do_nothing()
                .returning(CollaborationNoticeModel.notice_id)
            )
            if inserted is not None:
                await self._outbox(
                    notice.notice_id,
                    "financial.collaboration.notice_requested",
                    notice.assignment_id,
                    {"notice_id": str(notice.notice_id)},
                    notice.created_at,
                    session=db,
                )
        if schedule is not None:
            await db.execute(
                insert(CollaborationReleaseScheduleModel).values(
                    **asdict(schedule)
                )
            )

    @staticmethod
    async def _outbox(
        event_id, event_type, assignment_id, payload, at, *, session
    ):
        await session.execute(
            insert(OutboxEventModel).values(
                event_id=event_id,
                event_type=event_type,
                aggregate_id=str(assignment_id),
                aggregate_type="collaboration",
                payload=payload,
                created_at=at,
            )
        )
