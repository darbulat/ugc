"""Manual allocation and user-initiated disclosure in the order card."""

from dataclasses import dataclass, replace

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.paid_selection_delivery import (
    PaidSelectionDelivery,
    _message,
)
from ugc_bot.application.services.paid_selection_interest import (
    PaidSelectionInterestService,
)
from ugc_bot.infrastructure.db.creator_invite_models import (
    INVITES,
    MANUAL_READY,
)
from ugc_bot.infrastructure.db.invite_handoff_models import STAFF_DELIVERIES
from ugc_bot.infrastructure.db.models import (
    ManagerOrderModel,
    OrderItemModel,
    OrderModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.creator_invites import (
    contact_job_query,
    invitation,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.invite_handoff import (
    creator_destination,
    handoff_installed,
    public_telegram,
    save_sharing,
    sharing_state,
    track_visit,
)
from ugc_bot.infrastructure.db.repositories.invite_partners import (
    attach_opened_partner,
)
from ugc_bot.infrastructure.db.repositories.invite_preview import (
    PREVIEW_CONSENT,
    confirm_preview,
    preview_order,
    preview_positions,
)


@dataclass
class CreatorInviteService:
    selection: PaidSelectionInterestService
    delivery: PaidSelectionDelivery
    transactions: TransactionManager
    clock: Clock

    async def preview(self, identity, user_id):
        async with self.transactions.transaction() as session:
            db = _session(session)
            return await invitation(db, identity, self.clock.now(), user_id)

    async def open_invite(self, identity, user_id):
        async with self.transactions.transaction() as session:
            db = _session(session)
            now = self.clock.now()
            row = await invitation(db, identity, now, user_id)
            if (
                user_id
                and row["status"] == "active"
                and await handoff_installed(db)
            ):
                await db.run_sync(attach_opened_partner, identity, user_id, now)
                await track_visit(db, identity, user_id, now)
            return row

    async def creator_contact(self, identity, user_id):
        async with self.transactions.transaction() as session:
            db = _session(session)
            if not await handoff_installed(db):
                return None
            return await creator_destination(
                db, identity, user_id, self.clock.now()
            )

    @staticmethod
    async def _owner(db, principal):
        user = await db.get(UserModel, principal.user_id)
        require_current_principal(
            principal,
            principal.user_id,
            user.user_id if user else None,
            user.telegram_id if user else None,
            None,
        )
        if user is None or user.status != "active":
            raise PermissionError("invite_order_unavailable")
        return user

    async def client_sharing(self, principal, order_id, enabled=None):
        async with self.transactions.transaction() as session:
            db = _session(session)
            if not await handoff_installed(db):
                raise ValueError("invite_handoff_unavailable")
            user = await self._owner(db, principal)
            if enabled is not None:
                await save_sharing(db, order_id, user, enabled)
            shared = await sharing_state(db, order_id, user)
            staff = (
                (
                    await db.execute(
                        select(
                            INVITES.c.id,
                            OrderItemModel.ordinal,
                            STAFF_DELIVERIES.c.accepted_at,
                        )
                        .join(
                            OrderItemModel,
                            OrderItemModel.paid_item_id == INVITES.c.item_id,
                        )
                        .outerjoin(
                            STAFF_DELIVERIES,
                            STAFF_DELIVERIES.c.delivery_id == INVITES.c.id,
                        )
                        .where(
                            INVITES.c.order_id == order_id,
                            INVITES.c.reported_at.is_not(None),
                            INVITES.c.consented_at.is_(None),
                            OrderItemModel.selection_state == "paid",
                        )
                        .order_by(OrderItemModel.ordinal)
                    )
                )
                .mappings()
                .all()
            )
            return {
                "enabled": shared,
                "telegram": public_telegram(user.telegram),
                "staff": [dict(row) for row in staff],
            }

    async def acknowledge_staff_contact(self, principal, identity):
        from ugc_bot.infrastructure.db.repositories.correction_funding import (
            require_forward_clear,
        )

        async with self.transactions.transaction() as session:
            db = _session(session)
            user = await self._owner(db, principal)
            item = (
                await db.execute(
                    select(
                        OrderItemModel.paid_item_id,
                        OrderModel.order_id,
                        PaymentModel.payment_id,
                        INVITES.c.reported_at,
                        INVITES.c.consented_at,
                        OrderModel.status.label("order_status"),
                    )
                    .select_from(INVITES)
                    .join(OrderModel, OrderModel.order_id == INVITES.c.order_id)
                    .join(
                        OrderItemModel,
                        OrderItemModel.paid_item_id == INVITES.c.item_id,
                    )
                    .join(
                        PaymentModel,
                        PaymentModel.order_id == OrderModel.order_id,
                    )
                    .where(
                        INVITES.c.id == identity,
                        OrderModel.advertiser_id == user.user_id,
                        OrderModel.status.in_(("active", "closed")),
                        OrderModel.complimentary.is_(False),
                        OrderItemModel.captured_at.is_not(None),
                        PaymentModel.status == "paid",
                    )
                    .with_for_update(of=OrderModel)
                )
            ).one_or_none()
            if item is None or item.reported_at is None:
                raise ValueError("creator_invite_contact_unavailable")
            present = await db.scalar(
                select(STAFF_DELIVERIES.c.delivery_id).where(
                    STAFF_DELIVERIES.c.paid_item_id == item.paid_item_id
                )
            )
            if present == identity:
                return item.order_id
            if (
                present is not None
                or item.consented_at is not None
                or item.order_status != "active"
            ):
                raise ValueError("creator_invite_contact_unavailable")
            await require_forward_clear(item.paid_item_id, session=db)
            await db.execute(
                insert(STAFF_DELIVERIES).values(
                    paid_item_id=item.paid_item_id,
                    delivery_id=identity,
                    order_id=item.order_id,
                    payment_id=item.payment_id,
                    client_id=user.user_id,
                    accepted_at=self.clock.now(),
                )
            )
            return item.order_id

    async def accept(self, identity, user_id):
        row = await self.preview(identity, user_id)
        if row["complimentary"]:
            await self._accept_preview(identity, user_id, row["order_id"])
            await self._attach_confirmed_partner(identity, user_id)
            return None
        result = await self.selection.respond(
            row["order_id"], user_id, invite_id=identity
        )
        if result is None:
            raise ValueError("creator_invite_unavailable")
        await self._attach_confirmed_partner(identity, user_id)
        return result

    async def _attach_confirmed_partner(self, identity, user_id):
        async with self.transactions.transaction() as session:
            await _session(session).run_sync(
                lambda db: attach_opened_partner(
                    db, identity, user_id, self.clock.now(), confirmed=True
                )
            )

    async def _accept_preview(self, identity, user_id, order_id):
        async with self.transactions.transaction() as session:
            db = _session(session)
            order = await db.scalar(
                select(OrderModel)
                .where(OrderModel.order_id == order_id, preview_order())
                .with_for_update()
            )
            if order is None or user_id == order.advertiser_id:
                raise ValueError("creator_invite_unavailable")
            current = await invitation(
                db, identity, self.clock.now(), user_id, lock=True
            )
            await confirm_preview(db, current, user_id, self.clock.now())

    async def preview_card(self, principal, order_id):
        async with self.transactions.transaction() as session:
            db = _session(session)
            user = await db.get(UserModel, principal.user_id)
            require_current_principal(
                principal,
                principal.user_id,
                user.user_id if user else None,
                user.telegram_id if user else None,
                None,
            )
            return await preview_positions(db, order_id, principal.user_id)

    async def claim_manager_notice(self, identity):
        """One notification attempt after a creator confirms in Telegram."""
        async with self.transactions.transaction() as session:
            db = _session(session)
            address = await db.scalar(
                select(UserModel.telegram_id)
                .join(
                    ManagerOrderModel,
                    ManagerOrderModel.user_id == UserModel.user_id,
                )
                .join(
                    INVITES,
                    (INVITES.c.manager_id == UserModel.user_id)
                    & (INVITES.c.order_id == ManagerOrderModel.order_id),
                )
                .join(OrderModel, OrderModel.order_id == INVITES.c.order_id)
                .where(
                    INVITES.c.id == identity,
                    UserModel.status == "active",
                    UserModel.user_id != OrderModel.advertiser_id,
                )
            )
            if not address or not str(address).isdecimal():
                return None
            notice = (
                await db.execute(
                    update(INVITES)
                    .where(
                        INVITES.c.id == identity,
                        (
                            INVITES.c.consented_at.is_not(None)
                            | (
                                (INVITES.c.consent_source == PREVIEW_CONSENT)
                                & select(OrderModel.order_id)
                                .where(
                                    OrderModel.order_id == INVITES.c.order_id,
                                    preview_order(),
                                )
                                .exists()
                            )
                        ),
                        INVITES.c.manager_notice_at.is_(None),
                    )
                    .values(manager_notice_at=self.clock.now())
                    .returning(INVITES.c.order_id, INVITES.c.item_id)
                )
            ).one_or_none()
            if notice is None:
                return None
            ordinal = await db.scalar(
                select(OrderItemModel.ordinal).where(
                    OrderItemModel.paid_item_id == notice.item_id
                )
            )
            return int(address), notice.order_id, ordinal

    async def reported_contact(self, principal, identity):
        order_id, _ = await self._reported_contact(principal, identity)
        return order_id

    async def reported_contact_text(self, principal, identity):
        _, contact = await self._reported_contact(principal, identity)
        return contact

    async def _reported_contact(self, principal, identity):
        from ugc_bot.infrastructure.db.models import (
            ItemAssignmentModel,
        )
        from ugc_bot.infrastructure.db.repositories.correction_funding import (
            require_forward_clear,
        )

        async with self.transactions.transaction() as session:
            db = _session(session)
            user = await db.get(UserModel, principal.user_id)
            require_current_principal(
                principal,
                principal.user_id,
                user.user_id if user else None,
                user.telegram_id if user else None,
                None,
            )
            row = (
                (
                    await db.execute(
                        select(INVITES)
                        .join(
                            OrderModel,
                            OrderModel.order_id == INVITES.c.order_id,
                        )
                        .join(
                            OrderItemModel,
                            OrderItemModel.paid_item_id == INVITES.c.item_id,
                        )
                        .outerjoin(
                            ItemAssignmentModel,
                            (
                                ItemAssignmentModel.paid_item_id
                                == OrderItemModel.paid_item_id
                            )
                            & ItemAssignmentModel.valid_to.is_(None),
                        )
                        .where(
                            INVITES.c.id == identity,
                            INVITES.c.reported_at.is_not(None),
                            INVITES.c.consented_at.is_(None),
                            OrderModel.advertiser_id == principal.user_id,
                            OrderModel.status.in_(("active", "closed")),
                            OrderItemModel.selection_state == "paid",
                            ItemAssignmentModel.assignment_id.is_(None),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ValueError("creator_invite_contact_unavailable")
            await require_forward_clear(row["item_id"], session=db)
            return row["order_id"], "\n".join(
                (
                    "Контакт добавлен командой после согласия в переписке.",
                    row["creator_name"] or "",
                    "Instagram: https://instagram.com/" + row["instagram"],
                    "Telegram: @" + row["telegram"],
                )
            )

    async def card_contact(self, principal, assignment_id, transport):
        async with self.transactions.transaction() as session:
            db = _session(session)
            user = await db.get(UserModel, principal.user_id)
            require_current_principal(
                principal,
                principal.user_id,
                user.user_id if user else None,
                user.telegram_id if user else None,
                None,
            )
            query = contact_job_query(principal.user_id, assignment_id)
            job = (await db.execute(query)).one_or_none()
            if job is None:
                raise ValueError("creator_invite_contact_unavailable")
        if job.state in (MANUAL_READY, "sending"):
            attempt = await self.delivery.prepare(job.job_id, card_request=True)
            if (
                attempt is None
                or attempt.channel != "telegram"
                or attempt.address != principal.external_id
            ):
                raise ValueError("creator_invite_contact_unavailable")
            await self.delivery.deliver(attempt, transport=transport)
            async with self.transactions.transaction() as session:
                db = _session(session)
                current = (await db.execute(query)).one_or_none()
                if current is None or current.state != "accepted":
                    raise ValueError("creator_invite_contact_unavailable")
            return
        if job.state != "accepted":
            raise ValueError("creator_invite_contact_unavailable")
        async with self.transactions.transaction() as session:
            db = _session(session)
            source = await self.delivery.repository.lock_source(
                job.job_id, self.clock.now(), session=db
            )
            current = (await db.execute(query)).one_or_none()
            if (
                source is None
                or current is None
                or current.state != "accepted"
                or source.invalid_reason != "selection_already_delivered"
                or source.contact is None
                or source.contact.channel != "telegram"
                or source.contact.address != principal.external_id
            ):
                raise ValueError("creator_invite_contact_unavailable")
            attempt = await self.delivery.repository.attempt(
                current.current_attempt_id, session=db
            )
            message = replace(attempt, text=_message(source))
        await transport.send(message)
