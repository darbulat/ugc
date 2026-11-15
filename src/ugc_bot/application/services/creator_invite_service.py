"""Manual allocation and user-initiated disclosure in the order card."""

from dataclasses import dataclass, replace

from sqlalchemy import select, update

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
from ugc_bot.infrastructure.db.models import (
    ManagerOrderModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.creator_invites import (
    contact_job_query,
    invitation,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


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

    async def accept(self, identity, user_id):
        row = await self.preview(identity, user_id)
        result = await self.selection.respond(
            row["order_id"], user_id, invite_id=identity
        )
        if result is None:
            raise ValueError("creator_invite_unavailable")
        return result

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
                        INVITES.c.consented_at.is_not(None),
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
                            OrderModel.status == "active",
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
